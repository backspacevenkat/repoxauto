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
        self.settings = None  # Load settings when starting

    async def _load_settings(self, session: AsyncSession):
        """Load settings from database"""
        try:
            from ..models.settings import SystemSettings
            result = await session.execute(select(SystemSettings).limit(1))
            settings = result.scalar_one_or_none()
            
            if not settings:
                # Create default settings if none exist
                settings = SystemSettings()
                session.add(settings)
                await session.commit()
                await session.refresh(settings)
            
            return {
                "maxWorkers": settings.max_concurrent_workers,
                "requestsPerWorker": settings.max_requests_per_worker,
                "requestInterval": settings.request_interval,
                "taskBatchSize": 5,  # Default batch size
                "retryAttempts": 3,  # Default retry attempts
                "retryDelay": 5      # Default retry delay in seconds
            }
        except Exception as e:
            logger.error(f"Error loading settings: {str(e)}")
            # Return default settings if database access fails
            return {
                "maxWorkers": 6,
                "requestsPerWorker": 900,
                "requestInterval": 15,
                "taskBatchSize": 5,
                "retryAttempts": 3,
                "retryDelay": 5
            }

    async def start(self, max_workers: int = None, requests_per_worker: int = None, request_interval: int = None):
        """Start the task queue processor with optional settings override"""
        if self.running:
            return
            
        # Stop any existing workers first
        await self.stop()
        
        try:
            # Create new session for startup
            async with self.session_maker() as session:
                async with session.begin():
                    # Initialize rate limiter with session maker
                    self.rate_limiter = RateLimiter(self.session_maker)
                    
                    # Load settings from database
                    self.settings = await self._load_settings(session)
                    
                    # Override settings if provided
                    if max_workers is not None:
                        self.settings["maxWorkers"] = max_workers
                    if requests_per_worker is not None:
                        self.settings["requestsPerWorker"] = requests_per_worker
                    if request_interval is not None:
                        self.settings["requestInterval"] = request_interval
                    
                    # Set running flag before creating workers
                    self.running = True
                    
                    # Now create workers
                    for _ in range(self.settings["maxWorkers"]):
                        worker = asyncio.create_task(self._worker_loop())
                        self.workers.append(worker)
                    
                    logger.info(f"Started task queue with settings: {self.settings}")
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

    async def _process_task_group(self, session, task_type: str, task_list: List[Task]):
        """Process a group of tasks of the same type with reduced flushes to improve throughput"""
        endpoint = await self._get_endpoint_for_task(task_type, session)
        
        # Get available worker accounts for this task type
        available_accounts = await self._get_available_worker_accounts(session, endpoint, len(task_list))
        if not available_accounts:
            logger.info(f"No available worker accounts for {task_type} tasks")
            return

        processing_tasks = []
        tasks_to_reassign = []
        
        # Update task statuses
        for task, account in zip(task_list, available_accounts):
            task.status = "running"
            task.worker_account_id = account.id
            task.started_at = datetime.utcnow()
            processing_tasks.append(self._process_task(session, task, account))

        # Process tasks concurrently
        if processing_tasks:
            results = await asyncio.gather(*processing_tasks, return_exceptions=True)
            
            # Handle results
            for task, result in zip(task_list, results):
                if result is None:
                    # Task needs to be reassigned due to missing credentials
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
            
            # Handle tasks that need reassignment
            if tasks_to_reassign:
                logger.info(f"Reassigning {len(tasks_to_reassign)} tasks due to worker validation issues")
                # Get new workers, excluding the ones that failed validation
                failed_worker_ids = set(task.worker_account_id for task in tasks_to_reassign)
                new_accounts = await self._get_available_worker_accounts(
                    session, 
                    endpoint, 
                    len(tasks_to_reassign)
                )
                new_accounts = [w for w in new_accounts if w.id not in failed_worker_ids]
                
                if new_accounts:
                    # Reassign tasks to new workers
                    for task, account in zip(tasks_to_reassign, new_accounts):
                        task.worker_account_id = account.id
                        task.status = "pending"  # Reset to pending for next attempt
                        task.started_at = None
                        session.add(task)
                else:
                    logger.warning("No additional workers available for task reassignment")

    async def _process_task_batch(self, session, tasks: List[Task]):
        """Process a batch of tasks within a transaction"""
        if not tasks:
            return
            
        # Group tasks by type
        task_groups = self._group_tasks_by_type(tasks)
        
        # Process each group
        for task_type, task_list in task_groups.items():
            await self._process_task_group(session, task_type, task_list)

    async def _worker_loop(self):
        """Main worker loop to process tasks in parallel"""
        while self.running:
            try:
                # Process tasks in transaction
                async with self.session_maker() as session:
                    async with session.begin():
                        # Get pending tasks with row-level locking
                        stmt = (
                            select(Task)
                            .with_for_update(skip_locked=True)
                            .where(
                                and_(
                                    Task.status == "pending",
                                    Task.worker_account_id != None,
                                    Task.retry_count < 3
                                )
                            )
                            .order_by(
                                Task.priority.desc(),
                                Task.created_at.asc()
                            )
                            .limit(10)
                        )
                        
                        result = await session.execute(stmt)
                        tasks = result.scalars().all()
                        
                        if not tasks:
                            await asyncio.sleep(0.1)
                            continue
                        
                        # Mark tasks as locked
                        for task in tasks:
                            task.status = "locked"
                            session.add(task)
                        
                        # Process tasks within transaction
                        await self._process_task_batch(session, tasks)

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

    async def _check_account_rate_limits(
        self,
        session: AsyncSession,
        account: Account,
        endpoint: str
    ) -> Tuple[bool, Optional[str], Optional[datetime]]:
        """Check if account has hit rate limits"""
        # Ensure settings are loaded
        if self.settings is None:
            self.settings = await self._load_settings(session)
            
        try:
            # For action accounts, use lower rate limits
            if endpoint in ["like_tweet", "retweet_tweet", "reply_tweet", "quote_tweet", "create_tweet", "follow_user", "send_dm"]:
                # For follow and DM actions, enforce stricter limits
                if endpoint == "follow_user":
                    # Check 15min rate limit - max 2 follows per 15 minutes per account
                    can_use_15min = await self.rate_limiter.check_rate_limit(
                        account_id=account.id,
                        action_type=endpoint,
                        window='15min',
                        limit=2
                    )
                    
                    # Check 24h rate limit - max 20 follows per day per account
                    can_use_24h = await self.rate_limiter.check_rate_limit(
                        account_id=account.id,
                        action_type=endpoint,
                        window='24h',
                        limit=20
                    )
                    
                    # Add mandatory delay between follow actions
                    last_action = await session.execute(
                        select(Action).where(
                            and_(
                                Action.account_id == account.id,
                                Action.action_type == endpoint,
                                Action.status == "completed"
                            )
                        ).order_by(Action.executed_at.desc()).limit(1)
                    )
                    last_action = last_action.scalar_one_or_none()
                    
                    if last_action and last_action.executed_at:
                        time_since_last = datetime.utcnow() - last_action.executed_at
                        if time_since_last < timedelta(minutes=15):
                            wait_time = timedelta(minutes=15) - time_since_last
                            return False, f"Must wait {int(wait_time.total_seconds())} seconds between follows", datetime.utcnow() + wait_time
                elif endpoint == "send_dm":
                    # Check 15min rate limit - max 1 DM per 15 minutes per account
                    can_use_15min = await self.rate_limiter.check_rate_limit(
                        account_id=account.id,
                        action_type=endpoint,
                        window='15min',
                        limit=1
                    )
                    
                    # Check 24h rate limit - max 24 DMs per day per account
                    can_use_24h = await self.rate_limiter.check_rate_limit(
                        account_id=account.id,
                        action_type=endpoint,
                        window='24h',
                        limit=24
                    )
                    
                    # Add mandatory delay between DM actions
                    last_action = await session.execute(
                        select(Action).where(
                            and_(
                                Action.account_id == account.id,
                                Action.action_type == endpoint,
                                Action.status == "completed"
                            )
                        ).order_by(Action.executed_at.desc()).limit(1)
                    )
                    last_action = last_action.scalar_one_or_none()
                    
                    if last_action and last_action.executed_at:
                        time_since_last = datetime.utcnow() - last_action.executed_at
                        if time_since_last < timedelta(minutes=15):
                            wait_time = timedelta(minutes=15) - time_since_last
                            return False, f"Must wait {int(wait_time.total_seconds())} seconds between DMs", datetime.utcnow() + wait_time
                else:
                    # Other tweet actions use standard limits
                    can_use_15min = await self.rate_limiter.check_rate_limit(
                        account_id=account.id,
                        action_type=endpoint,
                        window='15min',
                        limit=30
                    )
                    
                    can_use_24h = await self.rate_limiter.check_rate_limit(
                        account_id=account.id,
                        action_type=endpoint,
                        window='24h',
                        limit=300
                    )
            else:
                # For worker accounts doing search/scraping, use normal worker limits
                can_use_15min = await self.rate_limiter.check_rate_limit(
                    account_id=account.id,
                    action_type=endpoint,
                    window='15min',
                    limit=self.settings["requestsPerWorker"]
                )
                
                can_use_24h = await self.rate_limiter.check_rate_limit(
                    account_id=account.id,
                    action_type=endpoint,
                    window='24h',
                    limit=int(self.settings["requestsPerWorker"] * (24 * 60 / self.settings["requestInterval"]))
                )
            
            if not can_use_15min:
                return False, "15-minute rate limit exceeded", None
            if not can_use_24h:
                return False, "24-hour rate limit exceeded", None
            return True, None, None
            
        except Exception as e:
            logger.error(f"Error checking rate limits: {str(e)}")
            return False, str(e), None

    async def _get_available_worker_accounts(
        self,
        session: AsyncSession,
        endpoint: str,
        count: int
    ) -> List[Account]:
        """Get multiple available worker accounts for parallel processing"""
        # Query available workers with row-level locking
        stmt = (
            select(Account)
            .with_for_update(skip_locked=True)
            .where(
                and_(
                    Account.act_type == 'worker',
                    Account.is_worker == True,
                    Account.deleted_at.is_(None),
                    or_(
                        Account.validation_in_progress == ValidationState.COMPLETED,
                        Account.validation_in_progress == ValidationState.PENDING
                    )
                )
            )
            .order_by(
                Account.current_15min_requests.asc(),
                Account.total_tasks_completed.asc()
            )
        )
        
        result = await session.execute(stmt)
        all_accounts = result.scalars().all()

        # Filter accounts by rate limits
        available_accounts = []
        for account in all_accounts:
            can_use, _, _ = await self._check_account_rate_limits(session, account, endpoint)
            if can_use:
                available_accounts.append(account)
                account.last_task_time = datetime.utcnow()
                session.add(account)
                if len(available_accounts) >= count:
                    break

        return available_accounts

    async def _get_endpoint_for_task(self, task_type: str, session: AsyncSession) -> str:
        """Map task type to rate limit endpoint"""
        # Ensure settings are loaded
        if self.settings is None:
            self.settings = await self._load_settings(session)
            
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

    async def _process_task(
        self,
        session: AsyncSession,
        task: Task,
        account: Account
    ) -> dict:
        """Process a single task"""
        client = None
        try:
            proxy_config = account.get_proxy_config()

            # Check if worker has required credentials
            required_fields = {
                "auth_token": account.auth_token,
                "ct0": account.ct0
            }
            
            missing_fields = [field for field, value in required_fields.items() if not value]
            if missing_fields:
                logger.warning(f"Worker {account.account_no} missing required fields: {missing_fields}")
                task.status = "pending"  # Reset to pending so it can be picked up by another worker
                session.add(task)
                return None

            client = TwitterClient(
                account_no=account.account_no,
                auth_token=account.auth_token,
                ct0=account.ct0,
                consumer_key=account.consumer_key,
                consumer_secret=account.consumer_secret,
                bearer_token=account.bearer_token,
                access_token=account.access_token,
                access_token_secret=account.access_token_secret,
                client_id=account.client_id,
                proxy_config=proxy_config,
                user_agent=account.user_agent
            )

            endpoint = await self._get_endpoint_for_task(task.type, session)
            
            # Record action attempt for rate limiting
            input_params = task.input_params
            if isinstance(input_params, str):
                input_params = json.loads(input_params)
                
            # Only get/update action for tweet interaction tasks and follow actions
            action = None
            if task.type in ["like_tweet", "retweet_tweet", "reply_tweet", "quote_tweet", "create_tweet", "follow_user", "send_dm"]:
                action = await session.execute(
                    select(Action).where(Action.task_id == task.id)
                )
                action = action.scalar_one_or_none()

            if task.type == "search_trending":
                # Get trending topics
                result = await client.get_trending_topics()
                
                # Save trends to database if requested
                if input_params.get("save_to_db", False):
                    for trend in result.get('trends', []):
                        db_trend = TrendingTopic(
                            name=trend.get('name'),
                            tweet_volume=trend.get('tweet_volume'),
                            domain=trend.get('domain'),
                            meta_data=trend.get('metadata', {}),
                            timestamp=datetime.fromisoformat(result['timestamp']),
                            account_id=account.id
                        )
                        session.add(db_trend)
                    # Update task result
                    task.result = result
                
                return result

            elif task.type == "search_tweets":
                # Get search parameters
                keyword = input_params.get("keyword")
                count = input_params.get("count", 20)
                cursor = input_params.get("cursor")
                
                if not keyword:
                    raise ValueError("Keyword is required for tweet search")
                
                # Search tweets
                result = await client.get_topic_tweets(
                    keyword=keyword,
                    count=count,
                    cursor=cursor
                )
                
                # Save tweets to database if requested
                if input_params.get("save_to_db", False):
                    for tweet in result.get('tweets', []):
                        db_tweet = TopicTweet(
                            keyword=keyword,
                            tweet_id=tweet.get('id'),
                            tweet_data=tweet,
                            timestamp=datetime.fromisoformat(result['timestamp']),
                            account_id=account.id
                        )
                        session.add(db_tweet)
                    # Update task result
                    task.result = result
                
                return result

            elif task.type == "search_users":
                # Get search parameters
                keyword = input_params.get("keyword")
                count = input_params.get("count", 20)
                cursor = input_params.get("cursor")
                
                if not keyword:
                    raise ValueError("Keyword is required for user search")
                
                # Search users
                result = await client.search_users(
                    keyword=keyword,
                    count=count,
                    cursor=cursor
                )
                
                # Save users to database if requested
                if input_params.get("save_to_db", False):
                    for user in result.get('users', []):
                        db_user = SearchedUser(
                            keyword=keyword,
                            user_id=user.get('id'),
                            user_data=user,
                            timestamp=datetime.fromisoformat(result['timestamp']),
                            account_id=account.id
                        )
                        session.add(db_user)
                    # Update task result
                    task.result = result
                
                return result

            elif task.type == "scrape_profile":
                # Handle profile scraping logic and save complete profile data to MongoDB
                username = input_params.get("username")
                if not username:
                    raise ValueError("Username is required for scrape_profile task")
    
                # Get user profile using UserByScreenName endpoint
                variables = {
                    "screen_name": username,
                    "withSafetyModeUserFields": True
                }
                response = await client.graphql_request('UserByScreenName', variables)
    
                # Extract user data from GraphQL response
                user_data = response.get('data', {}).get('user', {}).get('result', {})
                if not user_data:
                    raise ValueError(f"User {username} not found")
    
                legacy = user_data.get('legacy', {})
    
                # Import MongoDB client and get the scraped profiles collection
                from ..mongodb_client import get_scraped_profiles_collection
                collection = get_scraped_profiles_collection()
    
                profile_doc = {
                    "username": username,
                    "screen_name": legacy.get('screen_name'),
                    "name": legacy.get('name'),
                    "description": legacy.get('description'),
                    "location": legacy.get('location'),
                    "url": legacy.get('url'),
                    "profile_image_url": legacy.get('profile_image_url_https'),
                    "profile_banner_url": legacy.get('profile_banner_url'),
                    "followers_count": legacy.get('followers_count'),
                    "following_count": legacy.get('friends_count'),
                    "tweets_count": legacy.get('statuses_count'),
                    "likes_count": legacy.get('favourites_count'),
                    "media_count": legacy.get('media_count'),
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat()
                }
    
                # Insert the document into MongoDB
                await collection.insert_one(profile_doc)
    
                return {
                    "username": username,
                    "profile_data": {
                        "id": user_data.get('rest_id'),
                        "screen_name": legacy.get('screen_name'),
                        "name": legacy.get('name'),
                        "description": legacy.get('description'),
                        "location": legacy.get('location'),
                        "url": legacy.get('url'),
                        "profile_image_url": legacy.get('profile_image_url_https'),
                        "profile_banner_url": legacy.get('profile_banner_url'),
                        "metrics": {
                            "followers_count": legacy.get('followers_count'),
                            "following_count": legacy.get('friends_count'),
                            "tweets_count": legacy.get('statuses_count'),
                            "likes_count": legacy.get('favourites_count'),
                            "media_count": legacy.get('media_count')
                        },
                        "verified": legacy.get('verified', False),
                        "protected": legacy.get('protected', False),
                        "created_at": legacy.get('created_at'),
                        "professional": user_data.get('professional', {}),
                        "verified_type": user_data.get('verified_type')
                    },
                    "mongo_saved": True
                }
                
            elif task.type in ["like_tweet", "retweet_tweet", "reply_tweet", "quote_tweet", "create_tweet", "follow_user", "send_dm"]:
                # Handle Twitter action tasks
                meta_data = input_params.get("meta_data", {})
                
                # Execute action based on type
                if task.type == "follow_user":
                    user = meta_data.get("user")
                    if not user:
                        raise ValueError("user required for follow action")
                    result = await client.follow_user(user)
                elif task.type == "like_tweet":
                    tweet_id = input_params.get("tweet_id")
                    result = await client.like_tweet(tweet_id)
                elif task.type == "retweet_tweet":
                    tweet_id = input_params.get("tweet_id")
                    if not tweet_id:
                        raise ValueError("tweet_id required for retweet action")
                    result = await client.retweet(tweet_id)
                elif task.type == "reply_tweet":
                    tweet_id = input_params.get("tweet_id")
                    text_content = meta_data.get("text_content")
                    media = meta_data.get("media")
                    if not text_content:
                        raise ValueError("text_content required for reply action")
                    if not tweet_id:
                        raise ValueError("tweet_id required for reply action")
                    result = await client.reply_tweet(tweet_id, text_content, media)
                elif task.type == "quote_tweet":
                    tweet_id = input_params.get("tweet_id")
                    text_content = meta_data.get("text_content")
                    media = meta_data.get("media")
                    if not text_content:
                        raise ValueError("text_content required for quote tweet")
                    if not tweet_id:
                        raise ValueError("tweet_id required for quote tweet")
                    result = await client.quote_tweet(tweet_id, text_content, media)
                elif task.type == "create_tweet":
                    text_content = meta_data.get("text_content")
                    media = meta_data.get("media")
                    if not text_content:
                        raise ValueError("text_content required for create tweet")
                    result = await client.create_tweet(text_content, media)
                elif task.type == "send_dm":
                    text_content = meta_data.get("text_content")
                    user = meta_data.get("user")
                    media = meta_data.get("media")
                    if not text_content:
                        raise ValueError("text_content required for DM")
                    if not user:
                        raise ValueError("user required for DM")
                    result = await client.send_dm(user, text_content, media)
                
                return result

            elif task.type == "scrape_tweets":
                # Handle tweet scraping logic and store complete tweet data in MongoDB
                username = input_params.get("username")
                if not username:
                    raise ValueError("Username is required for scrape_tweets task")
                
                count = min(max(input_params.get("count", 15), 1), 100)
                hours = min(max(input_params.get("hours", 24), 1), 168)
                max_replies = min(max(input_params.get("max_replies", 7), 0), 20)
                
                # Get tweets without replies
                tweets_data = await client.get_user_tweets(
                    username=username,
                    count=count,
                    hours=hours
                )
                
                # Format tweets for returning to caller
                formatted_tweets = []
                for tweet in tweets_data.get("tweets", []):
                    formatted_tweet = {
                        "id": tweet.get("id"),
                        "text": tweet.get("text"),
                        "created_at": tweet.get("created_at"),
                        "tweet_url": tweet.get("tweet_url"),
                        "author": tweet.get("author"),
                        "metrics": tweet.get("metrics", {}),
                        "media": tweet.get("media", []),
                        "urls": tweet.get("urls", []),
                        "retweeted_by": tweet.get("retweeted_by"),
                        "retweeted_at": tweet.get("retweeted_at"),
                        "quoted_tweet": tweet.get("quoted_tweet")
                    }
                    formatted_tweets.append(formatted_tweet)
                
                # Import MongoDB client and get the scraped tweets collection
                from ..mongodb_client import get_scraped_tweets_collection
                collection = get_scraped_tweets_collection()
    
                # Build documents for each tweet; include additional metadata like username and the timestamp of scrapping
                tweet_docs = []
                scrapped_at = datetime.utcnow().isoformat()
                for tweet in tweets_data.get("tweets", []):
                    tweet_doc = {
                        "tweet_id": tweet.get("id"),
                        "username": username,
                        "text": tweet.get("text"),
                        "created_at": tweet.get("created_at"),
                        "tweet_url": tweet.get("tweet_url"),
                        "metrics": tweet.get("metrics", {}),
                        "media": tweet.get("media", []),
                        "urls": tweet.get("urls", []),
                        "retweeted_by": tweet.get("retweeted_by"),
                        "retweeted_at": tweet.get("retweeted_at"),
                        "quoted_tweet": tweet.get("quoted_tweet"),
                        "scraped_at": scrapped_at
                    }
                    tweet_docs.append(tweet_doc)
    
                if tweet_docs:
                    await collection.insert_many(tweet_docs)
    
                return {
                    "username": username,
                    "tweets": formatted_tweets,
                    "next_cursor": tweets_data.get("next_cursor"),
                    "timestamp": tweets_data.get("timestamp"),
                    "mongo_saved": True
                }

            elif task.type == "update_profile":
                # Handle profile update task
                account_no = input_params.get("account_no")
                meta_data = input_params.get("meta_data", {})
                
                if not account_no:
                    raise ValueError("account_no is required for profile update")
                
                # Get profile update record
                profile_update_id = meta_data.get("profile_update_id")
                if not profile_update_id:
                    raise ValueError("profile_update_id is required in meta_data")
                
                logger.info(f"Processing profile update {profile_update_id} for account {account_no}")
                logger.info(f"Update parameters: {meta_data}")
                
                # Log the update attempt
                logger.info(f"Attempting profile update for account {account_no}")
                logger.info(f"Update parameters: {json.dumps(meta_data, indent=2)}")

                # Update profile using API
                result = await client.update_profile(
                    name=meta_data.get("name"),
                    description=meta_data.get("description"),
                    url=meta_data.get("url"),
                    location=meta_data.get("location"),
                    profile_image=meta_data.get("profile_image"),
                    profile_banner=meta_data.get("profile_banner"),
                    lang=meta_data.get("lang"),
                    new_login=meta_data.get("new_login")
                )
                
                # Log the result
                if result.get("success"):
                    logger.info(f"Successfully updated profile for account {account_no}")
                    logger.info(f"API Response: {json.dumps(result.get('responses', {}), indent=2)}")
                else:
                    error_msg = result.get('error', 'Unknown error')
                    logger.error(f"Failed to update profile for account {account_no}")
                    logger.error(f"Error: {error_msg}")
                    
                    # Check for rate limit errors
                    if result.get('rate_limited'):
                        retry_after = result.get('retry_after', 900)  # Default to 15 minutes
                        logger.warning(f"Rate limit hit, waiting {retry_after} seconds")
                        await asyncio.sleep(retry_after)
                
                # Update profile update record status
                try:
                    profile_update = await session.execute(
                        select(ProfileUpdate).where(ProfileUpdate.id == profile_update_id)
                    )
                    profile_update = profile_update.scalar_one_or_none()
                    if profile_update:
                        if result.get("success"):
                            logger.info(f"Profile update {profile_update_id} completed successfully")
                            profile_update.status = "completed"
                            profile_update.error = None
                        else:
                            error_msg = result.get("error", "Unknown error")
                            logger.error(f"Profile update {profile_update_id} failed: {error_msg}")
                            profile_update.status = "failed"
                            profile_update.error = error_msg
                            
                            # Check for rate limit errors
                            if "429" in error_msg or "rate limit" in error_msg.lower():
                                logger.warning(f"Rate limit hit for profile update {profile_update_id}")
                                # Update rate limit info in database
                                rate_limit_info = {
                                    "reset": (datetime.utcnow() + timedelta(minutes=15)).isoformat(),
                                    "remaining": 0,
                                    "limit": 1
                                }
                                await self.rate_limiter.update_rate_limit_info(account.id, endpoint, rate_limit_info)
                        
                        profile_update.completed_at = datetime.utcnow()
                        # Log final state
                        logger.info(f"Updated profile update record {profile_update_id} status to {profile_update.status}")

                        # Broadcast profile update status change
                        try:
                            from ..main import app
                            if hasattr(app.state, 'connection_manager'):
                                await app.state.connection_manager.broadcast({
                                    "type": "profile_update_status",
                                    "profile_update_id": profile_update_id,
                                    "status": profile_update.status,
                                    "error": profile_update.error
                                })
                        except Exception as broadcast_error:
                            logger.error(f"Error broadcasting profile update status: {broadcast_error}")
                except Exception as e:
                    logger.error(f"Error updating profile update record {profile_update_id}: {str(e)}")
                
                return result
                
            raise ValueError(f"Invalid task type: {task.type}")
        finally:
            if client:
                try:
                    await client.close()
                except Exception as e:
                    logger.error(f"Error closing client in task {task.id}: {str(e)}")

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
