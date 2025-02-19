import logging
from datetime import datetime, timedelta
from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from typing import Dict, Optional, List, Tuple, Union
from dataclasses import dataclass
import json

from ..models import Account, Action
from ..schemas.action import ActionCreate

logger = logging.getLogger(__name__)

@dataclass
class RateLimitConfig:
    per_user_per_15min: int
    per_user_per_hour: int
    per_user_per_day: int
    min_interval_seconds: int
    max_parallel_actions: int

# Comprehensive rate limit configurations for all action types
RATE_LIMITS = {
    # Profile updates - less restrictive than other actions
    "update_profile": RateLimitConfig(
        per_user_per_15min=4,     # Allow more frequent profile updates
        per_user_per_hour=16,     # Reasonable hourly limit
        per_user_per_day=100,     # High daily limit
        min_interval_seconds=300,  # 5 minutes between updates
        max_parallel_actions=1     # No parallel profile updates
    ),
    # DM action type - 1 per 15min, 1000 per day per user
    "send_dm": RateLimitConfig(
        per_user_per_15min=1,    # Maximum 1 DM per 15 minutes
        per_user_per_hour=4,     # Maximum 4 DMs per hour (buffer)
        per_user_per_day=1000,   # Maximum 1000 DMs per day per user
        min_interval_seconds=900, # Minimum 15 minutes between DMs
        max_parallel_actions=1    # No parallel DM actions
    ),
    # Follow action type - 1 per 15min, 50 per day
    "follow_user": RateLimitConfig(
        per_user_per_15min=1,    # Maximum 1 follow per 15 minutes
        per_user_per_hour=4,     # Maximum 4 follows per hour (buffer)
        per_user_per_day=50,     # Maximum 50 follows per day
        min_interval_seconds=900, # Minimum 15 minutes between follows
        max_parallel_actions=1    # No parallel follow actions
    ),
    # Like/RT - 1 per 15min each
    "like_tweet": RateLimitConfig(
        per_user_per_15min=1,    # Maximum 1 like per 15 minutes
        per_user_per_hour=4,     # Maximum 4 likes per hour (buffer)
        per_user_per_day=96,     # Maximum 96 likes per day (buffer)
        min_interval_seconds=900, # Minimum 15 minutes between likes
        max_parallel_actions=1    # No parallel like actions
    ),
    "retweet_tweet": RateLimitConfig(
        per_user_per_15min=1,    # Maximum 1 retweet per 15 minutes
        per_user_per_hour=4,     # Maximum 4 retweets per hour (buffer)
        per_user_per_day=96,     # Maximum 96 retweets per day (buffer)
        min_interval_seconds=900, # Minimum 15 minutes between retweets
        max_parallel_actions=1    # No parallel retweet actions
    ),
    # Posts (Quote, Reply, Create) - 1 per 15min, 16 per day combined
    "reply_tweet": RateLimitConfig(
        per_user_per_15min=1,    # Maximum 1 post per 15 minutes
        per_user_per_hour=4,     # Maximum 4 posts per hour (buffer)
        per_user_per_day=16,     # Maximum 16 posts per day COMBINED
        min_interval_seconds=900, # Minimum 15 minutes between posts
        max_parallel_actions=1    # No parallel post actions
    ),
    "quote_tweet": RateLimitConfig(
        per_user_per_15min=1,    # Maximum 1 post per 15 minutes
        per_user_per_hour=4,     # Maximum 4 posts per hour (buffer)
        per_user_per_day=16,     # Maximum 16 posts per day COMBINED
        min_interval_seconds=900, # Minimum 15 minutes between posts
        max_parallel_actions=1    # No parallel post actions
    ),
    "create_tweet": RateLimitConfig(
        per_user_per_15min=1,    # Maximum 1 post per 15 minutes
        per_user_per_hour=4,     # Maximum 4 posts per hour (buffer)
        per_user_per_day=16,     # Maximum 16 posts per day COMBINED
        min_interval_seconds=900, # Minimum 15 minutes between posts
        max_parallel_actions=1    # No parallel post actions
    )
}

class RateLimitExceededError(Exception):
    def __init__(self, message: str, reset_time: datetime):
        self.message = message
        self.reset_time = reset_time
        super().__init__(self.message)

class RateLimiter:
    def __init__(self, session_maker):
        self.session_maker = session_maker
        self.logger = logging.getLogger(__name__)

    async def check_rate_limit(
        self,
        account_id: int,
        action_type: str,
        tweet_id: Optional[str] = None,
        window: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Union[Tuple[bool, Optional[str], Optional[datetime]], bool]:
        """
        Comprehensive rate limit check that handles both action-specific and general request rate limits
        """
        try:
            async with self.session_maker() as session:
                # Handle general request rate limits
                if window and limit:
                    try:
                        now = datetime.utcnow()
                        if window == '15min':
                            start_time = now - timedelta(minutes=15)
                        elif window == '24h':
                            start_time = now - timedelta(hours=24)
                        else:
                            return False
                        
                        # Get request count for the window
                        recent_actions = await session.execute(
                            select(Action).where(
                                and_(
                                    Action.account_id == account_id,
                                    Action.action_type == action_type,
                                    Action.created_at >= start_time
                                )
                            )
                        )
                        actions = recent_actions.scalars().all()
                        if len(actions) >= limit:
                            reset_time = start_time + (timedelta(minutes=15) if window == '15min' else timedelta(hours=24))
                            return False, f"{window} rate limit exceeded", reset_time
                        return True, None, None
                        
                    except Exception as e:
                        self.logger.error(f"Error checking request rate limit: {str(e)}")
                        return False, str(e), None

                # Handle action-specific rate limits
                now = datetime.utcnow()
                fifteen_mins_ago = now - timedelta(minutes=15)
                one_hour_ago = now - timedelta(hours=1)
                one_day_ago = now - timedelta(days=1)
                
                # Get rate limit config for action-specific limits
                rate_limit = RATE_LIMITS.get(action_type)
                if not rate_limit:
                    return False, f"Unknown action type: {action_type}", None
                
                # Get account's recent actions
                recent_actions = await session.execute(
                    select(Action).where(
                        and_(
                            Action.account_id == account_id,
                            Action.action_type == action_type,
                            Action.created_at >= one_day_ago,
                            Action.status != "failed"
                        )
                    ).order_by(Action.created_at.desc())
                )
                actions = recent_actions.scalars().all()
                
                # Check if action already performed on this tweet
                if tweet_id:
                    duplicate_action = await session.execute(
                        select(Action).where(
                            and_(
                                Action.account_id == account_id,
                                Action.action_type == action_type,
                                Action.tweet_id == tweet_id,
                                Action.status == "completed"
                            )
                        )
                    )
                    if duplicate_action.scalar_one_or_none():
                        return False, f"Already performed {action_type} on tweet {tweet_id}", None
            
                # Check minimum interval between actions
                if actions:
                    last_action = actions[0]  # Most recent action
                    time_since_last = (now - last_action.created_at).total_seconds()
                    if time_since_last < rate_limit.min_interval_seconds:
                        wait_time = rate_limit.min_interval_seconds - time_since_last
                        reset_time = last_action.created_at + timedelta(seconds=rate_limit.min_interval_seconds)
                        return False, f"Please wait {int(wait_time)} seconds before next action", reset_time
                
                # Check parallel actions limit
                running_actions = await session.execute(
                    select(func.count(Action.id)).where(
                        and_(
                            Action.account_id == account_id,
                            Action.action_type == action_type,
                            Action.status == "running"
                        )
                    )
                )
                if running_actions.scalar() >= rate_limit.max_parallel_actions:
                    return False, f"Too many parallel {action_type} actions", None
                
                # Check 15-minute limit
                actions_15min = [a for a in actions if a.created_at >= fifteen_mins_ago]
                if len(actions_15min) >= rate_limit.per_user_per_15min:
                    reset_time = fifteen_mins_ago + timedelta(minutes=15)
                    return False, "15-minute rate limit exceeded", reset_time
                
                # Check hourly limit
                actions_hour = [a for a in actions if a.created_at >= one_hour_ago]
                if len(actions_hour) >= rate_limit.per_user_per_hour:
                    reset_time = one_hour_ago + timedelta(hours=1)
                    return False, "Hourly rate limit exceeded", reset_time
                
                # Check daily limit
                if action_type in ["reply_tweet", "quote_tweet", "create_tweet"]:
                    # For posts, check combined daily limit across all post types
                    post_actions = await session.execute(
                        select(Action).where(
                            and_(
                                Action.account_id == account_id,
                                Action.action_type.in_(["reply_tweet", "quote_tweet", "create_tweet"]),
                                Action.created_at >= one_day_ago,
                                Action.status != "failed"
                            )
                        )
                    )
                    total_posts = len(post_actions.scalars().all())
                    if total_posts >= 16:  # Hard limit of 16 posts per day combined
                        reset_time = one_day_ago + timedelta(days=1)
                        return False, "Daily post limit exceeded (16 posts/day across all post types)", reset_time
                else:
                    # For other actions, check individual daily limits
                    if len(actions) >= rate_limit.per_user_per_day:
                        reset_time = one_day_ago + timedelta(days=1)
                        return False, "Daily rate limit exceeded", reset_time
                
                return True, None, None

        except Exception as e:
            self.logger.error(f"Error checking rate limit: {str(e)}")
            return False, f"Rate limit check error: {str(e)}", None

    async def update_rate_limit_info(
        self,
        account_id: int,
        action_type: str,
        rate_limit_info: Dict
    ) -> None:
        """Update rate limit information for an account"""
        try:
            async with self.session_maker() as session:
                account = await session.execute(
                    select(Account).where(Account.id == account_id)
                )
                account = account.scalar_one_or_none()
                
                if not account:
                    self.logger.error(f"Account {account_id} not found")
                    return
                
                # Initialize or update rate limits dictionary
                if not account.rate_limits:
                    account.rate_limits = {}
                
                # Update rate limit info with timestamp
                account.rate_limits[action_type] = {
                    "reset": rate_limit_info.get("reset"),
                    "remaining": rate_limit_info.get("remaining"),
                    "limit": rate_limit_info.get("limit"),
                    "updated_at": datetime.utcnow().isoformat()
                }
                
                await session.commit()
                
        except Exception as e:
            self.logger.error(f"Error updating rate limit info: {str(e)}")

    async def get_rate_limit_status(
        self,
        account_id: int,
        action_type: str
    ) -> Dict:
        """Get detailed rate limit status for an account"""
        try:
            async with self.session_maker() as session:
                now = datetime.utcnow()
                fifteen_mins_ago = now - timedelta(minutes=15)
                one_hour_ago = now - timedelta(hours=1)
                one_day_ago = now - timedelta(days=1)
                
                # Get rate limit config
                rate_limit = RATE_LIMITS.get(action_type)
                if not rate_limit:
                    return {"error": f"Unknown action type: {action_type}"}
                
                # Get account's actions
                actions_query = await session.execute(
                    select(Action).where(
                        and_(
                            Action.account_id == account_id,
                            Action.action_type == action_type,
                            Action.created_at >= one_day_ago,
                            Action.status != "failed"
                        )
                    ).order_by(Action.created_at.desc())
                )
                actions = actions_query.scalars().all()
                
                # Calculate usage and limits
                actions_15min = [a for a in actions if a.created_at >= fifteen_mins_ago]
                actions_hour = [a for a in actions if a.created_at >= one_hour_ago]
                
                # Get running actions count
                running_actions = await session.execute(
                    select(func.count(Action.id)).where(
                        and_(
                            Action.account_id == account_id,
                            Action.action_type == action_type,
                            Action.status == "running"
                        )
                    )
                )
                running_count = running_actions.scalar()
            
            # Calculate remaining limits
            remaining_15min = max(0, rate_limit.per_user_per_15min - len(actions_15min))
            remaining_hour = max(0, rate_limit.per_user_per_hour - len(actions_hour))
            
            # For posts, calculate combined daily limit
            if action_type in ["reply_tweet", "quote_tweet", "create_tweet"]:
                # Get all post actions for the day
                post_actions = await self.session.execute(
                    select(Action).where(
                        and_(
                            Action.account_id == account_id,
                            Action.action_type.in_(["reply_tweet", "quote_tweet", "create_tweet"]),
                            Action.created_at >= one_day_ago,
                            Action.status != "failed"
                        )
                    )
                )
                total_posts = len(post_actions.scalars().all())
                remaining_day = max(0, 16 - total_posts)  # Hard limit of 16 posts per day combined
            else:
                # For other actions, use individual daily limits
                remaining_day = max(0, rate_limit.per_user_per_day - len(actions))
            
            # Calculate next reset times
            next_15min_reset = fifteen_mins_ago + timedelta(minutes=15)
            next_hour_reset = one_hour_ago + timedelta(hours=1)
            next_day_reset = one_day_ago + timedelta(days=1)
            
            if actions:
                if actions_15min:
                    oldest_15min = min(actions_15min, key=lambda x: x.created_at).created_at
                    next_15min_reset = oldest_15min + timedelta(minutes=15)
                if actions_hour:
                    oldest_hour = min(actions_hour, key=lambda x: x.created_at).created_at
                    next_hour_reset = oldest_hour + timedelta(hours=1)
                oldest_day = min(actions, key=lambda x: x.created_at).created_at
                next_day_reset = oldest_day + timedelta(days=1)
            
            return {
                "current_usage": {
                    "15min": len(actions_15min),
                    "hour": len(actions_hour),
                    "day": len(actions),
                    "running": running_count
                },
                "limits": {
                    "15min": rate_limit.per_user_per_15min,
                    "hour": rate_limit.per_user_per_hour,
                    "day": rate_limit.per_user_per_day,
                    "parallel": rate_limit.max_parallel_actions
                },
                "remaining": {
                    "15min": remaining_15min,
                    "hour": remaining_hour,
                    "day": remaining_day,
                    "parallel": rate_limit.max_parallel_actions - running_count
                },
                "reset_times": {
                    "15min": next_15min_reset.isoformat(),
                    "hour": next_hour_reset.isoformat(),
                    "day": next_day_reset.isoformat()
                },
                "min_interval_seconds": rate_limit.min_interval_seconds,
                "last_action": actions[0].created_at.isoformat() if actions else None,
                "timestamp": now.isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Error getting rate limit status: {str(e)}")
            return {"error": str(e)}

    async def record_action_attempt(
        self,
        account_id: int,
        action_type: str,
        tweet_id: str,
        status: str = "running",
        error: Optional[str] = None,
        tweet_url: Optional[str] = None
    ) -> Action:
        """Record an action attempt in the database"""
        try:
            async with self.session_maker() as session:
                # If tweet_url not provided, construct it from tweet_id
                if not tweet_url and tweet_id:
                    tweet_url = f"https://twitter.com/i/web/status/{tweet_id}"

                # For tweet actions, require tweet_url
                if action_type in ["like_tweet", "retweet_tweet", "reply_tweet", "quote_tweet", "create_tweet"]:
                    if not tweet_url and tweet_id:
                        tweet_url = f"https://twitter.com/i/web/status/{tweet_id}"
                    action = Action(
                        account_id=account_id,
                        action_type=action_type,
                        tweet_id=tweet_id,
                        tweet_url=tweet_url,
                        status=status,
                        error_message=error,
                        created_at=datetime.utcnow()
                    )
                else:
                    # For non-tweet actions like profile scraping, use placeholder URL
                    action = Action(
                        account_id=account_id,
                        action_type=action_type,
                        tweet_id=None,
                        tweet_url="https://twitter.com",  # Placeholder URL for non-tweet actions
                        status=status,
                        error_message=error,
                        created_at=datetime.utcnow()
                    )
                
                session.add(action)
                await session.commit()
                await session.refresh(action)
                
                return action
                
        except Exception as e:
            self.logger.error(f"Error recording action attempt: {str(e)}")
            raise

    async def update_action_status(
        self,
        action_id: int,
        status: str,
        error: Optional[str] = None,
        rate_limit_info: Optional[Dict] = None
    ) -> None:
        """Update the status of an action and its associated task"""
        try:
            async with self.session_maker() as session:
                # Get action with task relationship
                action = await session.execute(
                    select(Action).where(Action.id == action_id)
                )
                action = action.scalar_one_or_none()
                
                if not action:
                    self.logger.error(f"Action {action_id} not found")
                    return
                
                # Update action status
                action.status = status
                action.error_message = error
                action.executed_at = datetime.utcnow()
                
                if rate_limit_info:
                    action.rate_limit_reset = rate_limit_info.get("reset")
                    action.rate_limit_remaining = rate_limit_info.get("remaining")
                
                # Update associated task if it exists
                if action.task_id:
                    from ..models.task import Task
                    task = await session.execute(
                        select(Task).where(Task.id == action.task_id)
                    )
                    task = task.scalar_one_or_none()
                    if task:
                        task.status = status
                        if error:
                            task.error = error
                        if status in ["completed", "failed", "cancelled"]:
                            task.completed_at = datetime.utcnow()
                
                await session.commit()
                
        except Exception as e:
            self.logger.error(f"Error updating action status: {str(e)}")

    async def cleanup_stale_actions(self) -> None:
        """Clean up stale running actions and their associated tasks"""
        try:
            async with self.session_maker() as session:
                one_hour_ago = datetime.utcnow() - timedelta(hours=1)
                
                # Get stale actions with their tasks
                stale_actions = await session.execute(
                    select(Action).where(
                        and_(
                            Action.status == "running",
                            Action.created_at <= one_hour_ago
                        )
                    )
                )
                
                for action in stale_actions.scalars():
                    # Update action status
                    action.status = "failed"
                    action.error_message = "Action timed out"
                    action.executed_at = datetime.utcnow()
                    
                    # Update associated task if it exists
                    if action.task_id:
                        from ..models.task import Task
                        task = await session.execute(
                            select(Task).where(Task.id == action.task_id)
                        )
                        task = task.scalar_one_or_none()
                        if task:
                            task.status = "failed"
                            task.error = "Action timed out"
                            task.completed_at = datetime.utcnow()
                
                await session.commit()
                
        except Exception as e:
            self.logger.error(f"Error cleaning up stale actions: {str(e)}")
