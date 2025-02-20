import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from sqlalchemy import select, and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from ..models.task import Task
from ..models.action import Action
from ..models.account import Account, ValidationState
from ..models.search import TrendingTopic, TopicTweet, SearchedUser
from ..models.profile_update import ProfileUpdate
from .session_manager import SessionManager
from .worker_pool import WorkerPool
from .task_processor import TaskProcessor
from .rate_limiter import RateLimiter
from .twitter_client import TwitterClient

logger = logging.getLogger(__name__)

class TaskQueue:
    def __init__(self, session_maker):
        self.session_manager = SessionManager(session_maker)
        self.rate_limiter = RateLimiter(session_maker)
        self.worker_pool = WorkerPool(self.rate_limiter)
        self.task_processor = TaskProcessor(self.worker_pool)
        self.running = False
        self.workers = []  # Worker tasks

    async def start(self, max_workers: int = None, requests_per_worker: int = None, request_interval: int = None):
        """Start the task queue processor with optional settings override"""
        if self.running:
            return
            
        # Stop any existing workers first
        await self.stop()
        
        try:
            # Initialize components in a transaction
            async with self.session_manager.transaction() as session:
                # Load settings and initialize worker pool
                await self.worker_pool.load_settings(session)
                
                # Override settings if provided
                if max_workers is not None:
                    self.worker_pool.settings["max_workers"] = max_workers
                if requests_per_worker is not None:
                    self.worker_pool.settings["requests_per_worker"] = requests_per_worker
                if request_interval is not None:
                    self.worker_pool.settings["request_interval"] = request_interval
                
                # Set running flag before creating workers
                self.running = True
                
                # Create worker tasks
                for _ in range(self.worker_pool.settings["max_workers"]):
                    worker = asyncio.create_task(self._worker_loop())
                    self.workers.append(worker)
                
                logger.info(f"Started task queue with settings: {self.worker_pool.settings}")
        except Exception as e:
            logger.error(f"Error starting task queue: {str(e)}")
            self.running = False
            raise

    async def stop(self):
        """Stop the task queue processor"""
        self.running = False
        
        # Cancel all workers
        if self.workers:
            for worker in self.workers:
                if not worker.done():
                    worker.cancel()
            
            # Wait for all workers to finish with timeout
            try:
                async with asyncio.timeout(5):  # 5 second timeout
                    await asyncio.gather(*self.workers, return_exceptions=True)
            except asyncio.TimeoutError:
                logger.warning("Some workers did not stop gracefully")
            except Exception as e:
                logger.error(f"Error stopping workers: {e}")
            finally:
                self.workers = []
        
        logger.info("Stopped task queue")

    def _group_tasks_by_type(self, tasks):
        """Group tasks by their type"""
        task_groups = {}
        for task in tasks:
            task_type = task.type
            if task_type not in task_groups:
                task_groups[task_type] = []
            task_groups[task_type].append(task)
        return task_groups

    async def _process_task_batch(self, session, tasks: List[Task]):
        """Process a batch of tasks within a transaction"""
        if not tasks:
            return
            
        # Delegate task processing to TaskProcessor
        await self.task_processor.process_batch(session, tasks)

    async def _worker_loop(self):
        """Main worker loop to process tasks in parallel"""
        while self.running:
            try:
                # Process tasks in transaction
                async with self.session_manager.transaction() as session:
                    # Get pending tasks with row-level locking
                    tasks = await self._get_pending_tasks(session)
                    
                    if not tasks:
                        await asyncio.sleep(0.1)
                        continue
                    
                    # Process tasks within transaction
                    await self.task_processor.process_batch(session, tasks)

            except asyncio.CancelledError:
                logger.info("Worker received cancel signal")
                raise
            except Exception as e:
                logger.error(f"Worker error: {str(e)}", exc_info=True)
                await asyncio.sleep(0.1)

    async def _get_next_task(self, session: AsyncSession) -> Optional[Task]:
        """Get next available task to process with row-level locking"""
        # Use SELECT FOR UPDATE SKIP LOCKED to prevent multiple workers from getting the same task
        stmt = select(Task).where(
            and_(
                Task.status == "pending",
                Task.retry_count < 3
            )
        ).order_by(
            Task.priority.desc(),
            Task.created_at.asc()
        ).limit(1).with_for_update(skip_locked=True)
        
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()
        
        if task:
            # Immediately mark the task as locked to prevent other workers from picking it up
            task.status = "locked"
        
        return task


    async def _get_endpoint_for_task(self, task_type: str, session: AsyncSession) -> str:
        """Map task type to rate limit endpoint"""
        endpoints = {
            # Action tasks with their own rate limits
            "like_tweet": "like_tweet",
            "retweet_tweet": "retweet_tweet",
            "reply_tweet": "reply_tweet",
            "quote_tweet": "quote_tweet",
            "create_tweet": "create_tweet",
            "follow_user": "follow_user",  # Follow actions use their own rate limit
            "send_dm": "send_dm",  # DM actions use their own rate limit
            "update_profile": "update_profile",  # Profile updates use their own rate limit
            
            # Non-tweet tasks use like_tweet for rate limiting
            "scrape_profile": "like_tweet",
            "scrape_tweets": "like_tweet",
            "search_trending": "like_tweet",
            "search_tweets": "like_tweet",
            "search_users": "like_tweet",
            "user_profile": "like_tweet",
            "user_tweets": "like_tweet"
        }
        if task_type not in endpoints:
            raise ValueError(f"Invalid task type: {task_type}")
        return endpoints[task_type]


    async def _get_pending_tasks(
        self,
        session: AsyncSession,
        batch_size: int = 10
    ) -> List[Task]:
        """Get pending tasks with row-level locking"""
        stmt = (
            select(Task)
            .with_for_update(skip_locked=True)
            .where(
                and_(
                    Task.status == "pending",
                    Task.retry_count < 3
                )
            )
            .order_by(
                Task.priority.desc(),
                Task.created_at.asc()
            )
            .limit(batch_size)
        )
    
        result = await session.execute(stmt)
        tasks = result.scalars().all()
    
        # Mark tasks as locked
        for task in tasks:
            task.status = "locked"
            session.add(task)
    
        return tasks

    async def get_pending_tasks(
        self,
        session: AsyncSession
    ) -> List[Task]:
        """Public method to get all pending tasks (without locking)"""
        stmt = select(Task).where(Task.status == "pending")
        result = await session.execute(stmt)
        return result.scalars().all()

    async def add_task(
        self,
        session: AsyncSession,
        task_type: str,
        input_params: dict,
        priority: int = 0
    ) -> Optional[Task]:
        """Add a new task to the queue"""
        try:
            # Create task
            task = Task(
                type=task_type,
                input_params=input_params,
                priority=priority,
                status="pending"
            )
            session.add(task)
            await session.flush()
            await session.refresh(task)

            # For tweet interaction tasks, follow actions, and DMs, create the action record
            if task_type in ["like_tweet", "retweet_tweet", "reply_tweet", "quote_tweet", "create_tweet", "follow_user", "send_dm"]:
                account_id = input_params.get("account_id")
                meta_data = input_params.get("meta_data", {})
                
                # Handle follow and DM actions differently
                if task_type in ['follow_user', 'send_dm']:
                    user = meta_data.get("user")
                    if not user:
                        logger.error(f"No user specified for {task_type} action")
                        await session.rollback()
                        return None
                        
                    # Check for existing follow action using JSON operator
                    existing_action = await session.execute(
                        select(Action).where(
                            and_(
                                Action.account_id == account_id,
                                Action.action_type == task_type,
                                Action.status.in_(["pending", "running", "locked"]),
                                Action.meta_data.like(f'%"user": "{user}"%')  # Simple JSON string matching
                            )
                        )
                    )
                    existing_action = existing_action.scalar_one_or_none()
                    
                    if existing_action:
                        logger.info(f"{task_type} action already exists for user {user}")
                        await session.rollback()
                        return None
                        
                    # Create action record for follow/DM
                    action = Action(
                        account_id=account_id,
                        task_id=task.id,
                        action_type=task_type,
                        status="pending",
                        meta_data=meta_data  # Use full meta_data for DMs to include text_content
                    )
                    session.add(action)
                    await session.flush()
                    
                    # Update task input_params to include meta_data
                    task.input_params = {
                        "account_id": account_id,
                        "meta_data": meta_data
                    }
                    await session.flush()
                    
                # Handle tweet actions
                else:
                    tweet_id = input_params.get("tweet_id")
                    if account_id and tweet_id:
                        # Check for existing tweet action
                        existing_action = await session.execute(
                            select(Action).where(
                                and_(
                                    Action.account_id == account_id,
                                    Action.action_type == task_type,
                                    Action.tweet_id == tweet_id,
                                    Action.status.in_(["pending", "running", "locked"])
                                )
                            )
                        )
                        existing_action = existing_action.scalar_one_or_none()
                        
                        if existing_action:
                            logger.info(f"Action already exists for {task_type} on tweet {tweet_id}")
                            await session.rollback()
                            return None

                        # Create action record for tweet action
                        action = Action(
                            account_id=account_id,
                            task_id=task.id,
                            action_type=task_type,
                            tweet_id=tweet_id,
                            tweet_url=input_params.get("tweet_url"),
                            status="pending",
                            meta_data=meta_data
                        )
                        session.add(action)
                        await session.flush()

            return task
        except Exception as e:
            logger.error(f"Error adding task: {str(e)}")
            await session.rollback()
            return None

    async def get_task_status(
        self,
        session: AsyncSession,
        task_id: int
    ) -> Optional[Task]:
        """Get status of a task"""
        stmt = (
            select(Task)
            .options(joinedload(Task.worker_account))
            .where(Task.id == task_id)
        )
        result = await session.execute(stmt)
        task = result.unique().scalar_one_or_none()
        
        if task:
            # Ensure the task is attached to the session
            await session.refresh(task)
        
        return task
