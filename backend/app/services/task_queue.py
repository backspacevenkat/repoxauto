import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from ..models.task import Task
from ..models.action import Action
from ..models.account import Account, ValidationState
from ..models.search import TrendingTopic, TopicTweet, SearchedUser
from .rate_limiter import RateLimiter
from .twitter_client import TwitterClient

logger = logging.getLogger(__name__)

class TaskQueue:
    def __init__(self, session_maker):
        self.session_maker = session_maker
        self.rate_limiter = None
        self.running = False
        self.workers = []
        self._lock = asyncio.Lock()
        self.settings = self._load_settings()

    def _load_settings(self):
        """Load settings from settings.json"""
        try:
            with open("settings.json", "r") as f:
                return json.load(f)
        except FileNotFoundError:
            # Return default settings
            return {
                "maxWorkers": 6,
                "requestsPerWorker": 900,
                "requestInterval": 15
            }

    async def start(self, max_workers: int = None, requests_per_worker: int = None, request_interval: int = None):
        """Start the task queue processor with optional settings override"""
        if self.running:
            return
        
        # Initialize rate limiter with a session
        async with self.session_maker() as session:
            self.rate_limiter = RateLimiter(session)
        
        # Reload settings in case they've changed
        self.settings = self._load_settings()
        
        # Override settings if provided
        if max_workers is not None:
            self.settings["maxWorkers"] = max_workers
        if requests_per_worker is not None:
            self.settings["requestsPerWorker"] = requests_per_worker
        if request_interval is not None:
            self.settings["requestInterval"] = request_interval
        
        self.running = True
        for _ in range(self.settings["maxWorkers"]):
            worker = asyncio.create_task(self._worker_loop())
            self.workers.append(worker)
        
        logger.info(f"Started task queue with settings: {self.settings}")

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

    async def _worker_loop(self):
        """Main worker loop to process tasks"""
        while self.running:
            try:
                # Create a fresh session for each iteration
                async with self.session_maker() as session:
                    async with self._lock:  # Use lock for task acquisition
                        # Get next available task
                        task = await self._get_next_task(session)
                        if not task:
                            await asyncio.sleep(1)
                            continue

                        endpoint = self._get_endpoint_for_task(task.type)
                        
                        # For action tasks, use the specified account
                        if task.type in ["like_tweet", "retweet_tweet", "reply_tweet", "quote_tweet", "create_tweet"]:
                            input_params = task.input_params
                            if isinstance(input_params, str):
                                input_params = json.loads(input_params)
                            
                            account_id = input_params.get("account_id")
                            if not account_id:
                                logger.error(f"No account_id specified in action task {task.id}")
                                task.status = "failed"
                                task.error = "No account_id specified in task"
                                await session.commit()
                                continue

                            account = await session.execute(
                                select(Account).where(Account.id == account_id)
                            )
                            account = account.scalar_one_or_none()
                            
                            if not account:
                                logger.error(f"Account {account_id} not found for task {task.id}")
                                task.status = "failed"
                                task.error = f"Account {account_id} not found"
                                await session.commit()
                                continue

                            # Check rate limits for action account
                            can_use, error_msg, reset_time = await self._check_account_rate_limits(session, account, endpoint)
                            if not can_use:
                                logger.info(f"Account {account.account_no} hit rate limit for {endpoint}: {error_msg}")
                                if reset_time:
                                    wait_time = (reset_time - datetime.utcnow()).total_seconds()
                                    if wait_time > 0:
                                        await asyncio.sleep(min(wait_time, 60))  # Wait up to 60 seconds
                                    else:
                                        await asyncio.sleep(5)
                                else:
                                    await asyncio.sleep(5)
                                continue
                        
                        # For other tasks (search, scraping), use worker accounts
                        else:
                            account = await self._get_available_worker_account(session, endpoint)
                            if not account:
                                await asyncio.sleep(5)
                                continue

                        # Mark task and action as running
                        task.status = "running"
                        task.worker_account_id = account.id
                        task.started_at = datetime.utcnow()
                        
                        # Update action status if this is an action task
                        if task.type in ["like_tweet", "retweet_tweet", "reply_tweet", "quote_tweet", "create_tweet"]:
                            action = await session.execute(
                                select(Action).where(Action.task_id == task.id)
                            )
                            action = action.scalar_one_or_none()
                            if action:
                                action.status = "running"
                                action.executed_at = datetime.utcnow()
                                
                                # Broadcast action update
                                try:
                                    from ..main import app
                                    if hasattr(app.state, 'connection_manager'):
                                        await app.state.connection_manager.broadcast({
                                            "type": "action_update",
                                            "action_id": action.id,
                                            "status": "running"
                                        })
                                except Exception as e:
                                    logger.error(f"Error broadcasting action update: {e}")
                        
                        await session.commit()
                        logger.info(f"Starting task {task.id} ({task.type}) with account {account.account_no}")

                    try:
                        # Process task outside the lock
                        result = await self._process_task(session, task, account)
                        
                        async with self._lock:  # Lock for updating task result
                            # Check if the action was successful
                            if isinstance(result, dict) and not result.get("success", True):
                                # Action failed
                                task.status = "failed"
                                task.error = result.get("error", "Unknown error")
                                task.retry_count += 1
                                task.completed_at = datetime.utcnow()
                                account.update_task_stats(False)
                                
                                # Only handle action tasks
                                if task.type in ["like_tweet", "retweet_tweet", "reply_tweet", "quote_tweet", "create_tweet"]:
                                    action = await session.execute(
                                        select(Action).where(Action.task_id == task.id)
                                    )
                                    action = action.scalar_one_or_none()
                                    if action:
                                        action.status = "failed"
                                        action.error_message = result.get("error", "Unknown error")
                                        action.executed_at = datetime.utcnow()
                                        
                                        # Broadcast action update
                                        try:
                                            from ..main import app
                                            if hasattr(app.state, 'connection_manager'):
                                                await app.state.connection_manager.broadcast({
                                                    "type": "action_update",
                                                    "action_id": action.id,
                                                    "status": "failed",
                                                    "error": result.get("error")
                                                })
                                        except Exception as broadcast_error:
                                            logger.error(f"Error broadcasting action failure: {broadcast_error}")
                            else:
                                # Action succeeded
                                task.status = "completed"
                                task.result = result
                                task.completed_at = datetime.utcnow()
                                account.update_task_stats(True)
                                
                                # Only handle action tasks
                                if task.type in ["like_tweet", "retweet_tweet", "reply_tweet", "quote_tweet", "create_tweet"]:
                                    action = await session.execute(
                                        select(Action).where(Action.task_id == task.id)
                                    )
                                    action = action.scalar_one_or_none()
                                    if action:
                                        action.status = "completed"
                                        action.executed_at = datetime.utcnow()
                                    
                                    # Broadcast action update
                                    try:
                                        from ..main import app
                                        if hasattr(app.state, 'connection_manager'):
                                            await app.state.connection_manager.broadcast({
                                                "type": "action_update",
                                                "action_id": action.id,
                                                "status": "completed"
                                            })
                                    except Exception as e:
                                        logger.error(f"Error broadcasting action update: {e}")
                            
                            await session.commit()
                            logger.info(f"Task {task.id} completed successfully")
                            
                            # Broadcast task update
                            try:
                                from ..main import app
                                if hasattr(app.state, 'connection_manager'):
                                    await app.state.connection_manager.broadcast({
                                        "type": "task_update",
                                        "task_id": task.id,
                                        "status": "completed",
                                        "result": result
                                    })
                            except Exception as e:
                                logger.error(f"Error broadcasting task update: {e}")
                    except Exception as e:
                        logger.error(f"Error processing task {task.id}: {str(e)}", exc_info=True)
                        async with self._lock:  # Lock for updating task error
                            task.status = "failed"
                            task.error = str(e)
                            task.retry_count += 1
                            task.completed_at = datetime.utcnow()
                            account.update_task_stats(False)
                            
                            # Update action status if this is an action task
                            if task.type in ["like_tweet", "retweet_tweet", "reply_tweet", "quote_tweet", "create_tweet"]:
                                action = await session.execute(
                                    select(Action).where(Action.task_id == task.id)
                                )
                                action = action.scalar_one_or_none()
                                if action:
                                    action.status = "failed"
                                    action.error_message = str(e)
                                    action.executed_at = datetime.utcnow()
                                    
                                    # Broadcast action update
                                    try:
                                        from ..main import app
                                        if hasattr(app.state, 'connection_manager'):
                                            await app.state.connection_manager.broadcast({
                                                "type": "action_update",
                                                "action_id": action.id,
                                                "status": "failed",
                                                "error": str(e)
                                            })
                                    except Exception as broadcast_error:
                                        logger.error(f"Error broadcasting action failure: {broadcast_error}")
                            
                            await session.commit()
                            
                            # Broadcast task update
                            try:
                                from ..main import app
                                if hasattr(app.state, 'connection_manager'):
                                    await app.state.connection_manager.broadcast({
                                        "type": "task_update",
                                        "task_id": task.id,
                                        "status": "failed",
                                        "error": str(e)
                                    })
                            except Exception as broadcast_error:
                                logger.error(f"Error broadcasting task failure: {broadcast_error}")

            except asyncio.CancelledError:
                logger.info("Worker received cancel signal")
                raise
            except Exception as e:
                logger.error(f"Worker error: {str(e)}", exc_info=True)
                await asyncio.sleep(1)

    async def _get_next_task(self, session: AsyncSession) -> Optional[Task]:
        """Get next available task to process with row-level locking"""
        try:
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
                await session.commit()
                
            return task
            
        except Exception as e:
            logger.error(f"Error getting next task: {str(e)}")
            await session.rollback()
            return None

    async def _check_account_rate_limits(
        self,
        session: AsyncSession,
        account: Account,
        endpoint: str
    ) -> Tuple[bool, Optional[str], Optional[datetime]]:
        """Check if account has hit rate limits"""
        try:
            # For action accounts, use lower rate limits
            if endpoint in ["like_tweet", "retweet_tweet", "reply_tweet", "quote_tweet", "create_tweet"]:
                # Check 15min rate limit - max 30 actions per 15 minutes
                can_use_15min = await self.rate_limiter.check_rate_limit(
                    account_id=account.id,
                    action_type=endpoint,
                    window='15min',
                    limit=30
                )
                
                # Check 24h rate limit - max 300 actions per day
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

    async def _get_available_worker_account(
        self,
        session: AsyncSession,
        endpoint: str
    ) -> Optional[Account]:
        """Get an available worker account that hasn't hit rate limits"""
        # Get all active worker accounts
        stmt = select(Account).where(
            and_(
                Account.act_type == 'worker',
                Account.is_active == True,
                Account.validation_in_progress == ValidationState.COMPLETED,
                Account.auth_token != None,
                Account.ct0 != None,
                Account.deleted_at == None
            )
        )
        
        result = await session.execute(stmt)
        accounts = result.scalars().all()
        
        if not accounts:
            return None

        # Get rate limit usage for each account
        available_accounts = []
        for account in accounts:
            can_use, error_msg, reset_time = await self._check_account_rate_limits(session, account, endpoint)
            if can_use:
                # Get current usage counts
                now = datetime.utcnow()
                fifteen_mins_ago = now - timedelta(minutes=15)
                one_day_ago = now - timedelta(days=1)
                
                # Get 15min usage
                actions_15min = await session.execute(
                    select(func.count(Action.id)).where(
                        and_(
                            Action.account_id == account.id,
                            Action.action_type == endpoint,
                            Action.created_at >= fifteen_mins_ago
                        )
                    )
                )
                usage_15min = actions_15min.scalar() or 0
                
                # Get 24h usage
                actions_24h = await session.execute(
                    select(func.count(Action.id)).where(
                        and_(
                            Action.account_id == account.id,
                            Action.action_type == endpoint,
                            Action.created_at >= one_day_ago
                        )
                    )
                )
                usage_24h = actions_24h.scalar() or 0
                
                # Calculate weighted score (70% weight to 15min, 30% to 24h)
                max_15min = self.settings["requestsPerWorker"]
                max_24h = self.settings["requestsPerWorker"] * (24 * 60 / self.settings["requestInterval"])
                
                score = (
                    0.7 * (usage_15min / max_15min) +
                    0.3 * (usage_24h / max_24h)
                )
                
                available_accounts.append((account, score))
        
        if not available_accounts:
            return None
            
        # Sort by weighted score to distribute tasks evenly
        available_accounts.sort(key=lambda x: x[1])
        
        # Log distribution for monitoring
        logger.info(f"Worker account distribution scores: {[(acc[0].account_no, acc[1]) for acc in available_accounts]}")
        
        return available_accounts[0][0]  # Return account with lowest weighted score

    def _get_endpoint_for_task(self, task_type: str) -> str:
        """Map task type to rate limit endpoint"""
        endpoints = {
            # All non-tweet tasks use like_tweet for rate limiting
            "scrape_profile": "like_tweet",
            "scrape_tweets": "like_tweet",
            "search_trending": "like_tweet",
            "search_tweets": "like_tweet",
            "search_users": "like_tweet",
            "user_profile": "like_tweet",
            "user_tweets": "like_tweet",
            "search_tweets": "like_tweet",
            "search_users": "like_tweet",
            
            # Tweet action tasks use their own types
            "like_tweet": "like_tweet",
            "retweet_tweet": "retweet_tweet",
            "reply_tweet": "reply_tweet",
            "quote_tweet": "quote_tweet",
            "create_tweet": "create_tweet"
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

            client = TwitterClient(
                account_no=account.account_no,
                auth_token=account.auth_token,
                ct0=account.ct0,
                proxy_config=proxy_config,
                user_agent=account.user_agent
            )

            endpoint = self._get_endpoint_for_task(task.type)
            
            # Record action attempt for rate limiting
            input_params = task.input_params
            if isinstance(input_params, str):
                input_params = json.loads(input_params)
                
            # Only get/update action for tweet interaction tasks
            action = None
            if task.type in ["like_tweet", "retweet_tweet", "reply_tweet", "quote_tweet", "create_tweet"]:
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
                    await session.commit()
                    
                    # Update task result
                    task.result = result
                    await session.commit()
                
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
                    await session.commit()
                    
                    # Update task result
                    task.result = result
                    await session.commit()
                
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
                    await session.commit()
                    
                    # Update task result
                    task.result = result
                    await session.commit()
                
                return result

            elif task.type == "scrape_profile":
                # Handle existing profile scraping logic
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
                    }
                }
                
            elif task.type in ["like_tweet", "retweet_tweet", "reply_tweet", "quote_tweet", "create_tweet"]:
                # Handle Twitter action tasks
                meta_data = input_params.get("meta_data", {})
                tweet_id = input_params.get("tweet_id")
                
                # Execute action based on type
                if task.type == "like_tweet":
                    result = await client.like_tweet(tweet_id)
                elif task.type == "retweet_tweet":
                    result = await client.retweet(tweet_id)
                elif task.type == "reply_tweet":
                    text_content = meta_data.get("text_content")
                    media = meta_data.get("media")
                    if not text_content:
                        raise ValueError("text_content required for reply action")
                    result = await client.reply_tweet(tweet_id, text_content, media)
                elif task.type == "quote_tweet":
                    text_content = meta_data.get("text_content")
                    media = meta_data.get("media")
                    if not text_content:
                        raise ValueError("text_content required for quote tweet")
                    result = await client.quote_tweet(tweet_id, text_content, media)
                elif task.type == "create_tweet":
                    text_content = meta_data.get("text_content")
                    media = meta_data.get("media")
                    if not text_content:
                        raise ValueError("text_content required for create tweet")
                    result = await client.create_tweet(text_content, media)
                
                return result

            elif task.type == "scrape_tweets":
                # Handle existing tweet scraping logic
                username = input_params.get("username")
                if not username:
                    raise ValueError("Username is required for scrape_tweets task")
                
                count = min(max(input_params.get("count", 15), 1), 100)
                hours = min(max(input_params.get("hours", 24), 1), 168)
                max_replies = min(max(input_params.get("max_replies", 7), 0), 20)
                
                tweets_data = await client.get_user_tweets(
                    username=username,
                    count=count,
                    hours=hours,
                    max_replies=max_replies
                )
                tweets = tweets_data.get("tweets", [])
                formatted_tweets = []
                for tweet in tweets:
                    # Format replies and threads
                    replies = []
                    if "replies" in tweet:
                        for reply in tweet["replies"]:
                            if reply["type"] == "thread":
                                # Format thread tweets
                                thread_tweets = []
                                for thread_tweet in reply["tweets"]:
                                    thread_tweets.append({
                                        "id": thread_tweet.get("id"),
                                        "text": thread_tweet.get("text"),
                                        "created_at": thread_tweet.get("created_at"),
                                        "tweet_url": thread_tweet.get("tweet_url"),
                                        "author": thread_tweet.get("author"),
                                        "metrics": thread_tweet.get("metrics", {}),
                                        "media": thread_tweet.get("media", []),
                                        "urls": thread_tweet.get("urls", [])
                                    })
                                replies.append({
                                    "type": "thread",
                                    "tweets": thread_tweets
                                })
                            else:
                                # Format single reply
                                reply_tweet = reply["tweet"]
                                replies.append({
                                    "type": "reply",
                                    "tweet": {
                                        "id": reply_tweet.get("id"),
                                        "text": reply_tweet.get("text"),
                                        "created_at": reply_tweet.get("created_at"),
                                        "tweet_url": reply_tweet.get("tweet_url"),
                                        "author": reply_tweet.get("author"),
                                        "metrics": reply_tweet.get("metrics", {}),
                                        "media": reply_tweet.get("media", []),
                                        "urls": reply_tweet.get("urls", [])
                                    }
                                })

                    formatted_tweet = {
                        "id": tweet.get("id"),
                        "text": tweet.get("text"),
                        "created_at": tweet.get("created_at"),
                        "tweet_url": tweet.get("tweet_url"),
                        "author": tweet.get("author"),
                        "metrics": {
                            "like_count": tweet.get("metrics", {}).get("like_count", 0),
                            "retweet_count": tweet.get("metrics", {}).get("retweet_count", 0),
                            "reply_count": tweet.get("metrics", {}).get("reply_count", 0),
                            "quote_count": tweet.get("metrics", {}).get("quote_count", 0),
                            "view_count": tweet.get("metrics", {}).get("view_count", 0)
                        },
                        "media": tweet.get("media", []),
                        "urls": tweet.get("urls", []),
                        "retweeted_by": tweet.get("retweeted_by"),
                        "retweeted_at": tweet.get("retweeted_at"),
                        "quoted_tweet": tweet.get("quoted_tweet"),
                        "replies": replies  # Add replies to tweet
                    }
                    formatted_tweets.append(formatted_tweet)

                return {
                    "username": username,
                    "tweets": formatted_tweets,
                    "next_cursor": tweets_data.get("next_cursor")
                }

            raise ValueError(f"Invalid task type: {task.type}")
        finally:
            if client:
                try:
                    await client.close()
                except Exception as e:
                    logger.error(f"Error closing client in task {task.id}: {str(e)}")

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

            # For tweet interaction tasks, create the action record
            if task_type in ["like_tweet", "retweet_tweet", "reply_tweet", "quote_tweet", "create_tweet"]:
                account_id = input_params.get("account_id")
                tweet_id = input_params.get("tweet_id")
                
                if account_id and tweet_id:
                    # Check for existing action
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
                        self.logger.info(f"Action already exists for {task_type} on tweet {tweet_id}")
                        await session.rollback()  # Rollback the task creation
                        return None

                    # Create action record
                    action = Action(
                        account_id=account_id,
                        task_id=task.id,
                        action_type=task_type,
                        tweet_id=tweet_id,
                        tweet_url=input_params.get("tweet_url"),
                        status="pending",
                        meta_data=input_params.get("meta_data", {})
                    )
                    session.add(action)
                    await session.flush()

            return task
        except Exception as e:
            self.logger.error(f"Error adding task: {str(e)}")
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

    async def get_pending_tasks(
        self,
        session: AsyncSession
    ) -> List[Task]:
        """Get all pending tasks"""
        stmt = select(Task).where(Task.status == "pending")
        result = await session.execute(stmt)
        return result.scalars().all()
