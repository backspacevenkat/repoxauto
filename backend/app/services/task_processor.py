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
