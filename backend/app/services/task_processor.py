import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.task import Task
from ..models.account import Account
from ..models.action import Action
from .worker_pool import WorkerPool
from .twitter_client import TwitterClient

logger = logging.getLogger(__name__)

class TaskProcessor:
    def __init__(self, worker_pool: WorkerPool):
        self.worker_pool = worker_pool

    def _group_tasks_by_type(self, tasks: List[Task]) -> Dict[str, List[Task]]:
        """Group tasks by their type"""
        task_groups = {}
        for task in tasks:
            task_type = task.type
            if task_type not in task_groups:
                task_groups[task_type] = []
            task_groups[task_type].append(task)
        return task_groups

    async def process_batch(
        self,
        session: AsyncSession,
        tasks: List[Task]
    ) -> None:
        """Process a batch of tasks within a transaction"""
        if not tasks:
            return

        # Group tasks by type for efficient processing
        task_groups = self._group_tasks_by_type(tasks)
        
        # Process each group
        for task_type, task_list in task_groups.items():
            await self._process_task_group(session, task_type, task_list)

    async def _process_task_group(
        self,
        session: AsyncSession,
        task_type: str,
        task_list: List[Task]
    ) -> None:
        """Process a group of tasks of the same type"""
        try:
            # Get available workers for this task type
            endpoint = await self._get_endpoint_for_task(task_type)
            available_workers = await self.worker_pool.get_available_workers(
                session,
                endpoint,
                len(task_list)
            )

            if not available_workers:
                logger.info(f"No available workers for {task_type} tasks")
                return

            # Prepare tasks for processing
            processing_tasks = []
            tasks_to_reassign = []

            # Update task statuses and create processing tasks
            for task, worker in zip(task_list, available_workers):
                task.status = "running"
                task.worker_account_id = worker.id
                task.started_at = datetime.utcnow()
                session.add(task)
                processing_tasks.append(self._process_task(session, task, worker))

            # Process tasks concurrently
            if processing_tasks:
                results = await asyncio.gather(*processing_tasks, return_exceptions=True)
                
                # Handle results
                for task, result in zip(task_list, results):
                    if result is None:
                        tasks_to_reassign.append(task)
                        continue
                        
                    if isinstance(result, Exception):
                        logger.error(f"Error processing task {task.id}: {str(result)}")
                        task.status = "failed"
                        task.error = str(result)
                        task.retry_count += 1
                        task.completed_at = datetime.utcnow()
                    else:
                        task.status = "completed"
                        task.result = result
                        task.completed_at = datetime.utcnow()
                    session.add(task)

                # Handle tasks that need reassignment
                if tasks_to_reassign:
                    await self._reassign_tasks(session, tasks_to_reassign, endpoint)

        except Exception as e:
            logger.error(f"Error processing task group: {str(e)}")
            raise

    async def _process_task(
        self,
        session: AsyncSession,
        task: Task,
        worker: Account
    ) -> Optional[Dict[str, Any]]:
        """Process a single task"""
        client = None
        try:
            # Validate worker credentials
            if not self._validate_worker_credentials(worker):
                task.status = "pending"
                session.add(task)
                return None

            # Create Twitter client
            client = self._create_twitter_client(worker)

            # Process task based on type
            result = await self._execute_task(session, task, worker, client)
            
            # Update task result
            if result:
                task.result = result
                session.add(task)

            return result

        except Exception as e:
            logger.error(f"Error processing task {task.id}: {str(e)}")
            raise
        finally:
            if client:
                try:
                    await client.close()
                except Exception as e:
                    logger.error(f"Error closing client for task {task.id}: {str(e)}")

    def _validate_worker_credentials(self, worker: Account) -> bool:
        """Validate worker credentials"""
        required_fields = {
            "auth_token": worker.auth_token,
            "ct0": worker.ct0
        }
        
        missing_fields = [field for field, value in required_fields.items() if not value]
        if missing_fields:
            logger.warning(f"Worker {worker.account_no} missing fields: {missing_fields}")
            return False
            
        return True

    def _create_twitter_client(self, worker: Account) -> TwitterClient:
        """Create Twitter client for worker"""
        return TwitterClient(
            account_no=worker.account_no,
            auth_token=worker.auth_token,
            ct0=worker.ct0,
            consumer_key=worker.consumer_key,
            consumer_secret=worker.consumer_secret,
            bearer_token=worker.bearer_token,
            access_token=worker.access_token,
            access_token_secret=worker.access_token_secret,
            client_id=worker.client_id,
            proxy_config=worker.get_proxy_config(),
            user_agent=worker.user_agent
        )

    async def _execute_task(
        self,
        session: AsyncSession,
        task: Task,
        worker: Account,
        client: TwitterClient
    ) -> Optional[Dict[str, Any]]:
        """Execute task with Twitter client"""
        # Get task parameters
        input_params = task.input_params
        if isinstance(input_params, str):
            input_params = json.loads(input_params)

        # Get action record for action tasks
        action = None
        if task.type in ["like_tweet", "retweet_tweet", "reply_tweet", "quote_tweet", "create_tweet", "follow_user", "send_dm"]:
            action = await session.execute(
                select(Action).where(Action.task_id == task.id)
            )
            action = action.scalar_one_or_none()

        # Execute task based on type
        if task.type == "follow_user":
            user = input_params.get("meta_data", {}).get("user")
            if not user:
                raise ValueError("user required for follow action")
            return await client.follow_user(user)

        elif task.type == "like_tweet":
            tweet_id = input_params.get("tweet_id")
            if not tweet_id:
                raise ValueError("tweet_id required for like action")
            return await client.like_tweet(tweet_id)

        # Add other task types here...

        raise ValueError(f"Invalid task type: {task.type}")

    async def _reassign_tasks(
        self,
        session: AsyncSession,
        tasks: List[Task],
        endpoint: str
    ) -> None:
        """Reassign failed tasks to new workers"""
        # Get new workers, excluding the ones that failed
        failed_worker_ids = set(task.worker_account_id for task in tasks)
        new_workers = await self.worker_pool.get_available_workers(
            session,
            endpoint,
            len(tasks)
        )
        new_workers = [w for w in new_workers if w.id not in failed_worker_ids]

        if new_workers:
            # Reassign tasks to new workers
            for task, worker in zip(tasks, new_workers):
                task.worker_account_id = worker.id
                task.status = "pending"
                task.started_at = None
                session.add(task)
        else:
            logger.warning("No additional workers available for task reassignment")

    async def _get_endpoint_for_task(self, task_type: str) -> str:
        """Map task type to rate limit endpoint"""
        endpoints = {
            "like_tweet": "like_tweet",
            "retweet_tweet": "retweet_tweet",
            "reply_tweet": "reply_tweet",
            "quote_tweet": "quote_tweet",
            "create_tweet": "create_tweet",
            "follow_user": "follow_user",
            "send_dm": "send_dm",
            "update_profile": "update_profile",
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
