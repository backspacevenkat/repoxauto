import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Union
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from .twitter_client import TwitterClient
from .rate_limiter import RateLimiter
from ..models import Account, Action
from ..schemas.action import ActionCreate

logger = logging.getLogger(__name__)

class ActionProcessor:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.rate_limiter = RateLimiter(session)
        self.logger = logging.getLogger(__name__)
        self._processing = False
        self._current_tasks = set()

    async def queue_action(
        self,
        account_id: int,
        action_type: str,
        tweet_url: Optional[str] = None,
        user: Optional[str] = None,
        priority: int = 0,
        meta_data: Optional[Dict] = None
    ) -> Tuple[bool, Optional[str], Optional[Action]]:
        """Queue a new action for processing"""
        try:
            tweet_id = None
            
            # Handle non-tweet actions (follow_user and send_dm) differently
            if action_type in ["follow_user", "send_dm"]:
                if not user:
                    return False, "user parameter required for follow action", None
                    
                # Check for existing pending or running follow action for this user
                existing_action = await self.session.execute(
                    select(Action).where(
                        and_(
                            Action.account_id == account_id,
                            Action.action_type == action_type,
                            Action.meta_data['user'].astext == user,
                            Action.status.in_(["pending", "running", "locked"])
                        )
                    )
                )
                existing_action = existing_action.scalar_one_or_none()
                
            else:
                # For tweet-based actions
                if action_type not in ["create_tweet", "follow_user", "send_dm"] and not tweet_url:
                    return False, "tweet_url required for tweet actions", None
                    
                # Extract tweet ID from URL
                try:
                    tweet_id = tweet_url.split("/status/")[-1].split("?")[0]
                except Exception as e:
                    return False, f"Invalid tweet URL: {str(e)}", None

                # Check for existing pending or running action
                existing_action = await self.session.execute(
                    select(Action).where(
                        and_(
                            Action.account_id == account_id,
                            Action.action_type == action_type,
                            Action.tweet_id == tweet_id,
                            Action.status.in_(["pending", "running", "locked"])
                        )
                    )
                )
                existing_action = existing_action.scalar_one_or_none()
            
            if existing_action:
                return False, "Action already queued or in progress", existing_action

            # Check rate limits before queuing
            is_allowed, error_msg, reset_time = await self.rate_limiter.check_rate_limit(
                account_id=account_id,
                action_type=action_type,
                tweet_id=tweet_id
            )
            
            if not is_allowed:
                return False, error_msg, None

            # Create action record
            action = await self.rate_limiter.record_action_attempt(
                account_id=account_id,
                action_type=action_type,
                tweet_id=tweet_id,
                tweet_url=tweet_url,
                status="pending"
            )
            
            # Add meta_data
            action_meta_data = {
                "priority": priority,
                "queued_at": datetime.utcnow().isoformat()
            }
            
            # Add tweet_url for tweet actions
            if tweet_url:
                action_meta_data["tweet_url"] = tweet_url
                
            # Add user for follow actions
            if user:
                action_meta_data["user"] = user
                
            # Add any additional meta_data
            if meta_data:
                action_meta_data.update(meta_data)
                
            action.meta_data = action_meta_data
            
            # Create associated task
            from ..models.task import Task
            task = Task(
                type=action_type,
                input_params={
                    "account_id": account_id,
                    "tweet_id": tweet_id,
                    "tweet_url": tweet_url,
                    "user": user,
                    "meta_data": action.meta_data
                },
                priority=priority,
                status="pending"
            )
            self.session.add(task)
            await self.session.flush()  # Get task ID
            
            # Link task to action
            action.task_id = task.id
            
            await self.session.commit()
            
            # Start processing if not already running
            if not self._processing:
                asyncio.create_task(self._process_queue())
            
            return True, None, action

        except Exception as e:
            self.logger.error(f"Error queuing action: {str(e)}")
            return False, str(e), None

    async def _process_queue(self) -> None:
        """Process queued actions"""
        if self._processing:
            return

        try:
            self._processing = True
            
            while True:
                # Get pending actions ordered by priority and creation time
                pending_actions = await self.session.execute(
                    select(Action)
                    .where(
                        and_(
                            Action.status == "pending",
                            Action.id.notin_(self._current_tasks)
                        )
                    )
                    .order_by(
                        Action.meta_data['priority'].desc(),
                        Action.created_at.asc()
                    )
                )
                actions = pending_actions.scalars().all()
                
                if not actions:
                    self.logger.info("No pending actions to process")
                    break

                # Process actions in parallel with rate limiting
                tasks = []
                for action in actions:
                    # Check if we can process this action now
                    is_allowed, error_msg, reset_time = await self.rate_limiter.check_rate_limit(
                        account_id=action.account_id,
                        action_type=action.action_type,
                        tweet_id=action.tweet_id
                    )
                    
                    if is_allowed:
                        self._current_tasks.add(action.id)
                        task = asyncio.create_task(
                            self._execute_action(action)
                        )
                        tasks.append(task)
                    else:
                        # Update action with rate limit info
                        action.error_message = error_msg
                        if reset_time:
                            action.meta_data = {
                                **(action.meta_data or {}),
                                "next_attempt_after": reset_time.isoformat()
                            }
                
                if tasks:
                    await asyncio.gather(*tasks)
                else:
                    # If no tasks could be executed, wait before checking again
                    await asyncio.sleep(5)

        except Exception as e:
            self.logger.error(f"Error processing action queue: {str(e)}")
        finally:
            self._processing = False
            self._current_tasks.clear()

    async def _execute_action(self, action: Action) -> None:
        """Execute a single action"""
        client = None
        try:
            # Get account using account_id
            stmt = select(Account).where(Account.id == action.account_id)
            result = await self.session.execute(stmt)
            account = result.scalar_one_or_none()
            
            if not account:
                await self.rate_limiter.update_action_status(
                    action.id,
                    "failed",
                    "Account not found"
                )
                return

            # Initialize Twitter client
            client = TwitterClient(
                account_no=account.account_no,
                auth_token=account.auth_token,
                ct0=account.ct0,
                proxy_config=account.get_proxy_config(),
                user_agent=account.user_agent
            )

            # Update action status to running
            action.status = "running"
            action.executed_at = datetime.utcnow()
            await self.session.commit()

            # Get meta_data for actions that need it
            meta_data = action.meta_data or {}
            text_content = meta_data.get('text_content')
            media = meta_data.get('media')
            api_method = meta_data.get('api_method', 'graphql')  # Default to graphql if not specified

            # Get source tweet data first (except for create_tweet and follow_user)
            if action.action_type not in ["create_tweet", "follow_user"]:
                try:
                    tweet_data = await client._process_tweet_data({
                        'rest_id': action.tweet_id,
                        'legacy': {}  # Will be populated by API
                    })
                    if tweet_data:
                        action.meta_data = {
                            **(action.meta_data or {}),
                            'source_tweet_data': tweet_data
                        }
                        await self.session.commit()
                except Exception as e:
                    self.logger.warning(f"Error getting source tweet data: {str(e)}")

            # Execute action based on type
            if action.action_type == "follow_user":
                user = meta_data.get('user')
                if not user:
                    raise ValueError("user required for follow action")
                result = await client.follow_user(user)
            elif action.action_type == "like_tweet":
                result = await client.like_tweet(action.tweet_id)
            elif action.action_type == "retweet_tweet":
                result = await client.retweet(action.tweet_id)
            elif action.action_type == "reply_tweet":
                if not text_content:
                    raise ValueError("text_content required for reply action")
                result = await client.reply_tweet(action.tweet_id, text_content, media, api_method)
            elif action.action_type == "quote_tweet":
                if not text_content:
                    raise ValueError("text_content required for quote tweet")
                result = await client.quote_tweet(action.tweet_id, text_content, media, api_method)
            elif action.action_type == "create_tweet":
                if not text_content:
                    raise ValueError("text_content required for create tweet")
                result = await client.create_tweet(text_content, media)
            elif action.action_type == "send_dm":
                user = meta_data.get('user')
                if not user:
                    raise ValueError("user required for DM action")
                if not text_content:
                    raise ValueError("text_content required for DM action")
                result = await client.send_dm(user, text_content, media)
            elif action.action_type == "profile_update":
                # Get profile update record
                profile_update_id = meta_data.get("profile_update_id")
                if not profile_update_id:
                    raise ValueError("profile_update_id required for profile update action")

                # Get profile update record
                from ..models.profile_update import ProfileUpdate
                profile_update = await self.session.get(ProfileUpdate, profile_update_id)
                if not profile_update:
                    raise ValueError(f"Profile update {profile_update_id} not found")

                # Update profile update status
                profile_update.status = "processing"
                await self.session.commit()

                try:
                    # Prepare update data (only include non-None fields)
                    update_data = {}
                    if profile_update.name is not None:
                        update_data["name"] = profile_update.name
                    if profile_update.description is not None:
                        update_data["description"] = profile_update.description
                    if profile_update.url is not None:
                        update_data["url"] = profile_update.url
                    if profile_update.location is not None:
                        update_data["location"] = profile_update.location
                    if profile_update.lang is not None:
                        update_data["lang"] = profile_update.lang

                    # Handle profile image if provided
                    if profile_update.profile_image_path:
                        media_ids = await client.upload_media([profile_update.profile_image_path])
                        if media_ids:
                            update_data["profile_image"] = media_ids[0]

                    # Handle profile banner if provided
                    if profile_update.profile_banner_path:
                        media_ids = await client.upload_media([profile_update.profile_banner_path])
                        if media_ids:
                            update_data["profile_banner"] = media_ids[0]

                    # Make the update request
                    result = await client.update_profile(**update_data)

                    # Update profile update status
                    profile_update.status = "completed" if result.get("success") else "failed"
                    profile_update.meta_data = {
                        **(profile_update.meta_data or {}),
                        "result": result,
                        "completed_at": datetime.utcnow().isoformat()
                    }
                    await self.session.commit()

                except Exception as e:
                    profile_update.status = "failed"
                    profile_update.meta_data = {
                        **(profile_update.meta_data or {}),
                        "error": str(e),
                        "failed_at": datetime.utcnow().isoformat()
                    }
                    await self.session.commit()
                    raise
            else:
                raise ValueError(f"Unknown action type: {action.action_type}")

            # Store result data if action succeeded
            if result["success"]:
                # Get account username for URL construction
                account = await self.session.get(Account, action.account_id)
                result_data = {
                    'success': True,
                    'tweet_id': result.get("tweet_id"),
                }

                # Construct result tweet URL based on action type
                if result.get("tweet_id") and account:
                    if action.action_type in ['reply_tweet', 'quote_tweet', 'create_tweet']:
                        result_data['tweet_url'] = f"https://twitter.com/{account.username}/status/{result['tweet_id']}"
                    elif action.action_type == 'retweet_tweet':
                        result_data['tweet_url'] = f"https://twitter.com/{account.username}/status/{result['tweet_id']}"

                # Store detailed tweet data if available
                try:
                    if result.get("tweet_id"):
                        result_tweet_data = await client._process_tweet_data({
                            'rest_id': result["tweet_id"],
                            'legacy': {}  # Will be populated by API
                        })
                        if result_tweet_data:
                            result_data['tweet_data'] = result_tweet_data
                except Exception as e:
                    self.logger.warning(f"Error getting result tweet data: {str(e)}")

                # Update action meta_data with result
                action.meta_data = {
                    **(action.meta_data or {}),
                    'result': result_data
                }

            # Update action status based on result
            if result["success"]:
                await self.rate_limiter.update_action_status(
                    action.id,
                    "completed",
                    rate_limit_info=result.get("rate_limit_info")
                )
            else:
                await self.rate_limiter.update_action_status(
                    action.id,
                    "failed",
                    error=result.get("error")
                )

        except Exception as e:
            self.logger.error(f"Error executing action {action.id}: {str(e)}")
            await self.rate_limiter.update_action_status(
                action.id,
                "failed",
                error=str(e)
            )
        finally:
            # Clean up
            self._current_tasks.discard(action.id)
            if client:
                try:
                    await client.close()
                except Exception as e:
                    self.logger.error(f"Error closing client: {str(e)}")

    async def get_action_status(self, action_id: int) -> Optional[Dict]:
        """Get status of a specific action"""
        try:
            action = await self.session.execute(
                select(Action).where(Action.id == action_id)
            )
            action = action.scalar_one_or_none()
            
            if not action:
                return None
            
            return {
                "id": action.id,
                "status": action.status,
                "type": action.action_type,
                "tweet_id": action.tweet_id,
                "created_at": action.created_at.isoformat(),
                "executed_at": action.executed_at.isoformat() if action.executed_at else None,
                "error": action.error_message,
                "meta_data": action.meta_data,
                "rate_limit_info": {
                    "reset": action.rate_limit_reset.isoformat() if action.rate_limit_reset else None,
                    "remaining": action.rate_limit_remaining
                } if action.rate_limit_reset or action.rate_limit_remaining else None
            }
            
        except Exception as e:
            self.logger.error(f"Error getting action status: {str(e)}")
            return None

    async def retry_failed_action(self, action_id: int) -> Tuple[bool, Optional[str]]:
        """Retry a failed action"""
        try:
            action = await self.session.execute(
                select(Action).where(Action.id == action_id)
            )
            action = action.scalar_one_or_none()
            
            if not action:
                return False, "Action not found"
            
            if action.status != "failed":
                return False, "Can only retry failed actions"
            
            # Create new action record for retry
            new_action = await self.rate_limiter.record_action_attempt(
                account_id=action.account_id,
                action_type=action.action_type,
                tweet_id=action.tweet_id,
                tweet_url=action.tweet_url,
                status="pending"
            )
            
            # Copy meta_data and mark as retry
            new_action.meta_data = {
                **(action.meta_data or {}),
                "retry_of": action.id,
                "retry_count": (action.meta_data or {}).get("retry_count", 0) + 1
            }
            
            # Create associated task for retry
            from ..models.task import Task
            task = Task(
                type=action.action_type,
                input_params={
                    "account_id": action.account_id,
                    "tweet_id": action.tweet_id,
                    "tweet_url": action.tweet_url,
                    "meta_data": new_action.meta_data
                },
                priority=action.meta_data.get("priority", 0),
                status="pending"
            )
            self.session.add(task)
            await self.session.flush()  # Get task ID
            
            # Link task to action
            new_action.task_id = task.id
            
            await self.session.commit()
            
            # Start processing if not already running
            if not self._processing:
                asyncio.create_task(self._process_queue())
            
            return True, None
            
        except Exception as e:
            self.logger.error(f"Error retrying action: {str(e)}")
            return False, str(e)

    async def cancel_pending_action(self, action_id: int) -> Tuple[bool, Optional[str]]:
        """Cancel a pending action"""
        try:
            action = await self.session.execute(
                select(Action).where(Action.id == action_id)
            )
            action = action.scalar_one_or_none()
            
            if not action:
                return False, "Action not found"
            
            if action.status != "pending":
                return False, "Can only cancel pending actions"
            
            # Get associated task
            from ..models.task import Task
            task = await self.session.execute(
                select(Task).where(Task.id == action.task_id)
            )
            task = task.scalar_one_or_none()
            
            # Update both action and task status
            action.status = "cancelled"
            action.executed_at = datetime.utcnow()
            
            if task:
                task.status = "cancelled"
                task.completed_at = datetime.utcnow()
            
            await self.session.commit()
            
            return True, None
            
        except Exception as e:
            self.logger.error(f"Error cancelling action: {str(e)}")
            return False, str(e)

    async def cleanup(self) -> None:
        """Cleanup tasks - call periodically"""
        try:
            # Clean up stale actions
            await self.rate_limiter.cleanup_stale_actions()
            
            # Reset processing flag if stuck
            if self._processing and not self._current_tasks:
                self._processing = False
            
        except Exception as e:
            self.logger.error(f"Error in cleanup: {str(e)}")
