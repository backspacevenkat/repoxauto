import logging
import asyncio
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.task import Task
from ..models.account import Account
from ..models.action import Action
from ..models.search import TrendingTopic, TopicTweet, SearchedUser
from ..models.profile_update import ProfileUpdate
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

            # Process tasks concurrently with timeout
            if processing_tasks:
                try:
                    # Set a generous timeout for task completion
                    results = await asyncio.wait_for(
                        asyncio.gather(*processing_tasks, return_exceptions=True),
                        timeout=1800  # 30 minute timeout
                    )

                    # Handle results
                    for task, result in zip(task_list, results):
                        if result is None:
                            tasks_to_reassign.append(task)
                            continue

                        # Check if it's an exception but the request actually succeeded
                        if isinstance(result, Exception):
                            error_str = str(result)
                            # Check if this is just a proxy warning with a successful request
                            if "Username and password must be escaped" in error_str:
                                # Extract response data between the warning and the end
                                response_data = error_str.split("HTTP/1.1 200 OK", 1)
                                if len(response_data) > 1 and "200 OK" in error_str:
                                    try:
                                        # Try to extract JSON response after 200 OK
                                        json_str = response_data[1].strip()
                                        if json_str:
                                            try:
                                                # Try to parse the actual response data
                                                response_json = json.loads(json_str)
                                                # This was actually a successful request with valid JSON data
                                                task.status = "completed"
                                                task.result = response_json  # Use the actual response data
                                                task.completed_at = datetime.utcnow()
                                                
                                                # Update worker metrics
                                                worker = await session.get(Account, task.worker_account_id)
                                                if worker:
                                                    worker.last_task_time = datetime.utcnow()
                                                    worker.total_tasks_completed += 1
                                                    # Log successful task completion
                                                    logger.info(f"Worker {worker.account_no} completed task {task.id} successfully")
                                                    session.add(worker)
                                            except json.JSONDecodeError:
                                                # Response wasn't valid JSON
                                                logger.error(f"Invalid JSON response for task {task.id}: {json_str[:200]}")
                                                if task.retry_count >= 3:
                                                    task.status = "failed"
                                                    task.error = "Failed to parse response after maximum retries"
                                                    task.completed_at = datetime.utcnow()
                                                    logger.error(f"Task {task.id} failed after maximum retries (invalid JSON)")
                                                else:
                                                    task.retry_count += 1
                                                    tasks_to_reassign.append(task)
                                                    logger.warning(f"Task {task.id} will retry (invalid JSON, attempt {task.retry_count}/3)")
                                        else:
                                            # No response data after 200 OK
                                            logger.error(f"Empty response data for task {task.id}")
                                            if task.retry_count >= 3:
                                                task.status = "failed"
                                                task.error = "Empty response after maximum retries"
                                                task.completed_at = datetime.utcnow()
                                                logger.error(f"Task {task.id} failed after maximum retries (empty response)")
                                            else:
                                                task.retry_count += 1
                                                tasks_to_reassign.append(task)
                                                logger.warning(f"Task {task.id} will retry (empty response, attempt {task.retry_count}/3)")
                                    except Exception as e:
                                        # Error parsing response data
                                        logger.error(f"Error parsing response data for task {task.id}: {str(e)}")
                                        if task.retry_count >= 3:
                                            task.status = "failed"
                                            task.error = f"Failed to parse response after maximum retries: {str(e)}"
                                            task.completed_at = datetime.utcnow()
                                            logger.error(f"Task {task.id} failed after maximum retries (parse error)")
                                        else:
                                            task.retry_count += 1
                                            tasks_to_reassign.append(task)
                                            logger.warning(f"Task {task.id} will retry (parse error, attempt {task.retry_count}/3)")
                                else:
                                    # Proxy error without success
                                    logger.error(f"Proxy error for task {task.id}: {error_str}")
                                    if task.retry_count >= 3:
                                        task.status = "failed"
                                        task.error = "Proxy error after maximum retries"
                                        task.completed_at = datetime.utcnow()
                                        logger.error(f"Task {task.id} failed after maximum retries (proxy error)")
                                    else:
                                        task.retry_count += 1
                                        tasks_to_reassign.append(task)
                                        logger.warning(f"Task {task.id} will retry (proxy error, attempt {task.retry_count}/3)")
                            else:
                                # Handle non-proxy errors
                                logger.error(f"Error processing task {task.id}: {error_str}")
                                
                                # Check for retryable errors
                                retryable_errors = [
                                    "timeout",
                                    "connection error",
                                    "network error",
                                    "rate limit",
                                    "429",
                                    "503",
                                    "502",
                                    "500"
                                ]
                                
                                is_retryable = any(err in error_str.lower() for err in retryable_errors)
                                
                                if is_retryable and task.retry_count < 3:
                                    task.retry_count += 1
                                    task.error = error_str
                                    tasks_to_reassign.append(task)
                                    logger.warning(f"Task {task.id} will retry (retryable error, attempt {task.retry_count}/3)")
                                else:
                                    task.status = "failed"
                                    task.error = error_str if not is_retryable else f"Error persisted after maximum retries: {error_str}"
                                    task.completed_at = datetime.utcnow()
                                    logger.error(f"Task {task.id} failed: {task.error}")
                        else:
                            task.status = "completed"
                            task.result = result
                            task.completed_at = datetime.utcnow()
                            
                            # Update worker's last task time and metrics
                            worker = await session.get(Account, task.worker_account_id)
                            if worker:
                                worker.last_task_time = datetime.utcnow()
                                worker.total_tasks_completed += 1
                                session.add(worker)
                                
                        session.add(task)
                except asyncio.TimeoutError:
                    logger.error("Task processing timed out")
                    
                    # Handle timeout for all tasks in batch
                    for task in task_list:
                        if task.retry_count >= 3:  # Max retries reached
                            task.status = "failed"
                            task.error = "Task failed after maximum retries (timeout)"
                            task.completed_at = datetime.utcnow()
                            logger.error(f"Task {task.id} failed after maximum retries (timeout)")
                        else:
                            task.status = "pending"  # Reset to pending for retry
                            task.error = "Task processing timed out"
                            task.retry_count += 1
                            logger.warning(f"Task {task.id} timed out (retry {task.retry_count}/3)")
                        
                        # Clear any partial results
                        task.result = None
                        session.add(task)
                        
                    # Reset workers for reuse
                    for worker in available_workers:
                        self.worker_pool.deactivate_worker(worker)
                        logger.info(f"Deactivated worker {worker.account_no} after timeout")

                    # Handle tasks that need reassignment (only non-failed tasks)
                    tasks_to_reassign.extend([t for t in task_list if t.status == "pending"])
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
                        account_id=worker.id
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
                        account_id=worker.id
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
                        account_id=worker.id
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
                            await self.rate_limiter.update_rate_limit_info(worker.id, endpoint, rate_limit_info)
                    
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

        # Handle Twitter action tasks
        elif task.type in ["like_tweet", "retweet_tweet", "reply_tweet", "quote_tweet", "create_tweet", "follow_user", "send_dm"]:
            meta_data = input_params.get("meta_data", {})
            
            if task.type == "follow_user":
                user = meta_data.get("user")
                if not user:
                    raise ValueError("user required for follow action")
                return await client.follow_user(user)
                
            elif task.type == "like_tweet":
                tweet_id = input_params.get("tweet_id")
                if not tweet_id:
                    raise ValueError("tweet_id required for like action")
                return await client.like_tweet(tweet_id)
                
            elif task.type == "retweet_tweet":
                tweet_id = input_params.get("tweet_id")
                if not tweet_id:
                    raise ValueError("tweet_id required for retweet action")
                return await client.retweet(tweet_id)
                
            elif task.type == "reply_tweet":
                tweet_id = input_params.get("tweet_id")
                text_content = meta_data.get("text_content")
                media = meta_data.get("media")
                if not text_content:
                    raise ValueError("text_content required for reply action")
                if not tweet_id:
                    raise ValueError("tweet_id required for reply action")
                return await client.reply_tweet(tweet_id, text_content, media)
                
            elif task.type == "quote_tweet":
                tweet_id = input_params.get("tweet_id")
                text_content = meta_data.get("text_content")
                media = meta_data.get("media")
                if not text_content:
                    raise ValueError("text_content required for quote tweet")
                if not tweet_id:
                    raise ValueError("tweet_id required for quote tweet")
                return await client.quote_tweet(tweet_id, text_content, media)
                
            elif task.type == "create_tweet":
                text_content = meta_data.get("text_content")
                media = meta_data.get("media")
                if not text_content:
                    raise ValueError("text_content required for create tweet")
                return await client.create_tweet(text_content, media)
                
            elif task.type == "send_dm":
                text_content = meta_data.get("text_content")
                user = meta_data.get("user")
                media = meta_data.get("media")
                if not text_content:
                    raise ValueError("text_content required for DM")
                if not user:
                    raise ValueError("user required for DM")
                return await client.send_dm(user, text_content, media)

        raise ValueError(f"Invalid task type: {task.type}")

    async def _reassign_tasks(
        self,
        session: AsyncSession,
        tasks: List[Task],
        endpoint: str
    ) -> None:
        """Reassign failed tasks to new workers, prioritizing original workers"""
        reassigned_count = 0
        for task in tasks:
            # Try to reassign to original worker
            if task.worker_account_id:
                worker = await session.get(Account, task.worker_account_id)
                if worker and await self.worker_pool._is_worker_available(session, worker, endpoint):
                    # Reset task state for retry with original worker
                    task.status = "pending"
                    task.started_at = None
                    task.error = None  # Clear any previous error
                    task.result = None  # Clear any partial results
                    logger.info(f"Reassigning task {task.id} to original worker {worker.account_no}")
                    session.add(task)
                    reassigned_count += 1
                    continue

            # If original worker not available, find a new one
            failed_worker_ids = set(task.worker_account_id for task in tasks)
            new_workers = await self.worker_pool.get_available_workers(
                session,
                endpoint,
                len(tasks) - reassigned_count
            )
            new_workers = [w for w in new_workers if w.id not in failed_worker_ids]

            if new_workers:
                # Reassign tasks to new workers
                for task, worker in zip(tasks, new_workers):
                    # Reset task state for retry with new worker
                    task.worker_account_id = worker.id
                    task.status = "pending"
                    task.started_at = None
                    task.error = None  # Clear any previous error
                    task.result = None  # Clear any partial results
                    logger.info(f"Reassigning task {task.id} to new worker {worker.account_no}")
                    session.add(task)
            else:
                logger.warning("No additional workers available for task reassignment")
                # Mark remaining tasks as failed if no workers available
                for task in tasks[reassigned_count:]:
                    task.status = "failed"
                    task.error = "No available workers for reassignment"
                    task.completed_at = datetime.utcnow()
                    logger.error(f"Task {task.id} failed: No available workers for reassignment")
                    session.add(task)

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
