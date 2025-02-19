import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from sqlalchemy import (
    select, and_, or_, func, text, update, case,
    Integer, cast, Text
)
import json
from sqlalchemy import JSON
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..models.follow_settings import FollowSettings
from ..models.follow_list import FollowList, FollowProgress, ListType
from ..models.account import Account
from .twitter_client import TwitterClient

logger = logging.getLogger(__name__)

class FollowScheduler:
    def __init__(self, db_session: async_sessionmaker[AsyncSession]):
        self.db_session = db_session
        self._running = False
        self._current_group = None
        self._next_group_start = None
        self._task = None
        self._lock = asyncio.Lock()
        self._settings = None  # Store current settings

    def is_running(self) -> bool:
        """Check if scheduler is running"""
        return self._running and self._task is not None and not self._task.done()

    async def start(self):
        """Start the follow scheduler"""
        if self.is_running():
            # Stop existing scheduler first
            await self.stop()
            logger.info("Stopped existing scheduler")

        # Reset state
        self._running = True
        self._current_group = None
        self._next_group_start = None

        try:
            # Activate accounts
            async with self.db_session() as session:
                async with session.begin():
                    try:
                        # Get settings for follow limits
                        settings = await session.execute(select(FollowSettings))
                        settings = settings.scalar_one_or_none()
                        if not settings:
                            logger.error("No follow settings found")
                            return
                        
                        # Store settings in instance
                        self._settings = settings
                        
                        # Ensure settings are active
                        if not settings.is_active:
                            logger.info("Follow system is disabled in settings")
                            return
                            
                        # Log current account status and settings
                        total_accounts = await session.scalar(
                            select(func.count(Account.id))
                            .where(Account.deleted_at.is_(None))
                        )
                        logger.info(f"Total available accounts: {total_accounts}")
                        
                        # Log accounts with credentials
                        accounts_with_creds = await session.scalar(
                            select(func.count(Account.id))
                            .where(
                                and_(
                                    Account.deleted_at.is_(None),
                                    Account.login.isnot(None),
                                    Account.auth_token.isnot(None),
                                    Account.ct0.isnot(None)
                                )
                            )
                        )
                        logger.info(f"Accounts with credentials: {accounts_with_creds}")
                        
                        # Log current settings
                        logger.info(f"Current settings - Max follows per day: {settings.max_follows_per_day}, "
                                f"Max following: {settings.max_following}, "
                                f"Interval minutes: {settings.interval_minutes}")
                        
                        # Build activation query with less restrictive checks
                        now = datetime.utcnow()
                        current_hour = now.hour
                        group = int(round(float(current_hour) / (24.0 / settings.schedule_groups))) % settings.schedule_groups
                        
                        # First update all active accounts
                        activation_query = (
                            update(Account)
                            .where(
                                and_(
                                    Account.deleted_at.is_(None),
                                    Account.login.isnot(None),
                                    Account.auth_token.isnot(None),
                                    Account.ct0.isnot(None)
                                )
                            )
                            .values(
                                is_active=True,
                                activated_at=now,
                                daily_follows=0,  # Reset daily follows
                                following_count=func.coalesce(Account.following_count, 0),  # Initialize if null
                                meta_data=text(f"""json_object(
                                    'group', '{group}',
                                    'updated_at', '{now.isoformat()}'
                                )"""),
                                updated_at=now
                            )
                        )
                        
                        # Log query for debugging
                        logger.info(f"Executing activation query: {str(activation_query)}")
                        
                        result = await session.execute(activation_query)
                        activated_count = result.rowcount
                        
                        # Get total active accounts
                        active_count = await session.scalar(
                            select(func.count(Account.id))
                            .where(Account.is_active.is_(True))
                        )
                        
                        logger.info(f"Activated {activated_count} new accounts, total active: {active_count}")
                        
                    except Exception as e:
                        logger.error(f"Error activating accounts: {e}")
                        raise
            
            # Start scheduler task
            self._task = asyncio.create_task(self._run_scheduler())
            logger.info("Follow scheduler started with fresh state")
            
        except Exception as e:
            logger.error(f"Error starting follow scheduler: {e}")
            self._running = False
            raise

    async def stop(self):
        """Stop the follow scheduler and clean up state"""
        logger.info("Stopping follow scheduler...")
        
        # Stop running
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        
        # Reset state
        self._current_group = None
        self._next_group_start = None
        
        # Deactivate accounts
        async with self.db_session() as session:
            try:
                await session.execute(
                    update(Account)
                    .where(Account.is_active.is_(True))
                    .values(is_active=False)
                )
                await session.commit()
                logger.info("Deactivated all accounts")
            except Exception as e:
                logger.error(f"Error deactivating accounts: {e}")
                await session.rollback()
        
        logger.info("Follow scheduler stopped and state cleaned up")

    async def reconfigure(self):
        """Reconfigure the scheduler with new settings"""
        logger.info("Reconfiguring follow scheduler...")
        
        was_running = self.is_running()
        
        # Stop current scheduler and clean up
        await self.stop()
        
        # Get latest settings
        async with self.db_session() as session:
            settings = await session.execute(select(FollowSettings))
            settings = settings.scalar_one_or_none()
            
            if not settings:
                logger.error("No follow settings found during reconfigure")
                return
            
            if not settings.is_active:
                logger.info("Follow system is disabled in settings")
                return
            
            logger.info(
                f"New settings - Groups: {settings.schedule_groups}, "
                f"Hours: {settings.schedule_hours}, "
                f"Internal ratio: {settings.internal_ratio}, "
                f"External ratio: {settings.external_ratio}"
            )
        
        # Only restart if it was running before or settings are active
        if was_running or settings.is_active:
            await self.start()
            logger.info("Follow scheduler restarted with new settings")
        else:
            logger.info("Follow scheduler remains stopped after reconfigure")

    async def get_active_group(self) -> Optional[int]:
        """Get currently active group number"""
        return self._current_group

    async def get_next_group_start(self) -> Optional[datetime]:
        """Get next group start time"""
        return self._next_group_start

    async def _run_scheduler(self):
        """Main scheduler loop"""
        try:
            while self._running:
                async with self._lock:
                    try:
                        # Get settings and process group in a single transaction
                        async with self.db_session() as session:
                            async with session.begin():
                                # Get settings
                                settings = await session.execute(select(FollowSettings))
                                settings = settings.scalar_one_or_none()
                                
                                if not settings or not settings.is_active:
                                    logger.info("Follow system not active or no settings found")
                                    await asyncio.sleep(60)
                                    continue

                                # Calculate schedule using settings
                                now = datetime.utcnow()
                                total_groups = max(1, settings.schedule_groups)
                                hours_per_group = int(max(1, min(24 / total_groups, settings.schedule_hours)))
                                
                                # Calculate current group based on UTC hour
                                current_hour = now.hour
                                new_group = int(round(float(current_hour) / (24.0 / settings.schedule_groups))) % settings.schedule_groups
                                
                                # Calculate group hours based on current hour
                                hours_per_group = int(round(24.0 / settings.schedule_groups))
                                group_start_hour = int(round(new_group * hours_per_group))
                                group_end_hour = int(round((new_group + 1) * hours_per_group))
                                
                                # Calculate next group transition time
                                next_group = (new_group + 1) % total_groups
                                next_group_hour = int(round(next_group * hours_per_group)) % 24
                                next_group_start = now.replace(
                                    hour=next_group_hour,
                                    minute=0,
                                    second=0,
                                    microsecond=0
                                )
                                if next_group_start <= now:
                                    next_group_start += timedelta(days=1)
                                    
                                logger.info(
                                    f"Schedule: {total_groups} groups, {hours_per_group}h each. "
                                    f"Current group {new_group + 1} ({group_start_hour:02d}:00-{group_end_hour:02d}:00 UTC)"
                                )
                                
                                # Log group transition and update settings
                                if self._current_group != new_group:
                                    logger.info(f"Transitioning from group {self._current_group} to {new_group}")
                                    self._current_group = new_group
                                    self._next_group_start = next_group_start
                                    
                                    # Store settings
                                    self._settings = settings
                                    
                                    # Update active accounts with new group
                                    # Update active accounts with new group using same formula
                                    await session.execute(
                                        update(Account)
                                        .where(Account.is_active.is_(True))
                                        .values(
                                            meta_data=text(f"""json_object(
                                                'group', CAST(CAST(ROUND(CAST(strftime('%H', CURRENT_TIMESTAMP) AS FLOAT) / (24.0 / {settings.schedule_groups})) AS INTEGER) % {settings.schedule_groups} AS TEXT),
                                                'updated_at', '{now.isoformat()}'
                                            )""")
                                        )
                                    )
                                    logger.info(f"Updated account group assignments to group {new_group}")
                    except Exception as e:
                        logger.error(f"Error in scheduler transaction: {e}")
                        await asyncio.sleep(60)
                        continue

                    # Reset daily follows at midnight UTC in a separate transaction
                    if current_hour == 0:
                        async with self.db_session() as session:
                            async with session.begin():
                                await session.execute(
                                    update(Account)
                                    .where(Account.is_active.is_(True))
                                    .values(daily_follows=0)
                                )
                                await session.commit()
                                logger.info("Reset daily follow counts at UTC midnight")
                        
                        # Calculate next group using same formula
                        hours_per_group = int(round(24.0 / settings.schedule_groups))
                        current_hour = now.hour
                        new_group = int(round(float(current_hour) / (24.0 / settings.schedule_groups))) % settings.schedule_groups
                        next_group = (new_group + 1) % settings.schedule_groups
                        
                        # Calculate next group start time
                        next_group_hour = int(next_group * hours_per_group)
                        self._next_group_start = now.replace(
                            hour=next_group_hour,
                            minute=0,
                            second=0,
                            microsecond=0
                        )
                        if self._next_group_start <= now:
                            self._next_group_start += timedelta(days=1)

                    logger.info(
                        f"Follow Schedule: Group {self._current_group + 1}/{total_groups} "
                        f"(Hours {group_start_hour:02d}:00-{group_end_hour:02d}:00) "
                        f"active until {self._next_group_start.strftime('%Y-%m-%d %H:%M:%S')}"
                    )

                    # Get and process accounts for current group
                    accounts = await self._get_group_accounts(self._current_group, total_groups)
                    if not accounts:
                        logger.info(f"No accounts to process in group {self._current_group + 1}, waiting 60s")
                        await asyncio.sleep(60)
                        continue

                    logger.info(f"Starting follow process for {len(accounts)} accounts in group {self._current_group + 1}")

                # Process accounts in parallel with rate limit awareness
                tasks = []
                for account in accounts:
                    if not self._running:
                        break

                    # Check if account is rate limited
                    if account.rate_limit_until and account.rate_limit_until > datetime.utcnow():
                        logger.info(f"Account {account.login} is rate limited until {account.rate_limit_until}")
                        continue

                    # Check last follow time and scheduled follows
                    async with self.db_session() as session:
                        # Get last completed follow
                        last_follow = await session.execute(
                            select(FollowProgress.followed_at)
                            .where(
                                and_(
                                    FollowProgress.account_id == account.id,
                                    FollowProgress.status == "completed"
                                )
                            )
                            .order_by(FollowProgress.followed_at.desc())
                            .limit(1)
                        )
                        last_follow_time = last_follow.scalar()

                        # Get next scheduled follow
                        next_scheduled = await session.execute(
                            select(FollowProgress)
                            .where(
                                and_(
                                    FollowProgress.account_id == account.id,
                                    FollowProgress.status == "pending",
                                    FollowProgress.scheduled_for.isnot(None)
                                )
                            )
                            .order_by(FollowProgress.scheduled_for.asc())
                            .limit(1)
                        )
                        next_follow = next_scheduled.scalar_one_or_none()

                    now = datetime.utcnow()
                    
                    # Check if we need to wait for scheduled follow
                    if next_follow and next_follow.scheduled_for > now:
                        wait_time = (next_follow.scheduled_for - now).total_seconds()
                        logger.info(f"Account {account.login} has scheduled follow at {next_follow.scheduled_for}, waiting {wait_time:.1f}s")
                        continue

                    # Check if we need to wait for 15-min gap
                    if last_follow_time:
                        time_since_last = (now - last_follow_time).total_seconds()
                        if time_since_last < 900:  # 15 minutes in seconds
                            logger.info(f"Account {account.login} needs to wait {900 - time_since_last:.1f}s before next follow")
                            continue

                    logger.info(f"Starting follow process for account {account.login}")
                    task = asyncio.create_task(self._process_account(account, settings))
                    tasks.append(task)

                if tasks:
                    # Wait for all tasks to complete
                    await asyncio.gather(*tasks)
                    logger.info(f"Completed processing {len(tasks)} accounts")
                else:
                    logger.info("No accounts ready to follow, waiting...")
                    await asyncio.sleep(60)

                # Wait before checking next group
                logger.info(f"Completed processing group {self._current_group + 1}, waiting 60s")
                await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("Scheduler cancelled")
            raise
        except Exception as e:
            logger.error(f"Scheduler error: {str(e)}")
            self._running = False

    async def _get_group_accounts(self, group: int, total_groups: int) -> List[Account]:
        """Get accounts for current group with detailed logging"""
        group_info = f"Group {group + 1}/{total_groups}"
        logger.info(f"Getting accounts for {group_info}")
        
        settings = self._settings
        if not settings:
            logger.error("No settings available for group distribution")
            return []
            
        # Calculate time window for this group
        hours_per_group = settings.schedule_hours
        group_start = datetime.utcnow() - timedelta(hours=hours_per_group)
        
        async with self.db_session() as session:
            # Get active accounts for this group with basic requirements
            query = select(Account).where(
                and_(
                    Account.is_active.is_(True),     # Must be active
                    Account.deleted_at.is_(None),    # Not deleted
                    Account.auth_token.isnot(None),  # Has auth token
                    Account.ct0.isnot(None),         # Has ct0 token
                    Account.login.isnot(None),       # Has username
                    # Add group assignment check using SQLite JSON
                                    text("CAST(CASE WHEN meta_data IS NULL OR json_valid(meta_data) = 0 THEN '0' ELSE json_extract(meta_data, '$.group') END AS INTEGER) = :group")
                )
            ).params(group=group).order_by(
                func.random()  # Randomize for even distribution
            )
            
            # Log query for debugging
            logger.info(f"Group accounts query: {query}")
            
            # Execute query and get all accounts
            result = await session.execute(query)
            all_accounts = result.scalars().all()
            
            if not all_accounts:
                logger.warning(f"No active accounts found for {group_info}")
                return []
                
            if not settings:
                logger.error("No settings available for account distribution")
                return []

            # Calculate accounts per group based on settings
            total_accounts = len(all_accounts)
            accounts_per_group = max(1, total_accounts // settings.schedule_groups)
            
            # Get slice of accounts for current group
            start_idx = group * accounts_per_group
            end_idx = start_idx + accounts_per_group
            group_accounts = all_accounts[start_idx:end_idx]
            
            if not group_accounts:
                logger.warning(f"No accounts assigned to {group_info}")
                return []
                
            # Log distribution details
            logger.info(f"Account distribution: {total_accounts} total accounts, "
                       f"{accounts_per_group} accounts per group, "
                       f"{len(group_accounts)} accounts in current group")
            
            # Log account distribution
            logger.info(f"Total active accounts: {len(all_accounts)}")
            logger.info(f"Assigned {len(group_accounts)} accounts to {group_info}")
            
            # Get follow counts for assigned accounts
            for account in group_accounts:
                logger.info(
                    f"[{group_info}] Account {account.login}: "
                    f"Following {account.following_count or 0}, "
                    f"Daily follows: {account.daily_follows or 0}"
                )
            
            return group_accounts  # Return all accounts in the group

    async def _can_account_follow(self, account: Account, settings: FollowSettings) -> bool:
        """Check if account can follow more users"""
        try:
            # Check rate limits
            if account.is_rate_limited:
                logger.info(f"Account {account.login} is rate limited")
                return False

            # Check account's last follow time
            async with self.db_session() as session:
                last_follow = await session.execute(
                    select(FollowProgress.followed_at)
                    .where(
                        and_(
                            FollowProgress.account_id == account.id,
                            FollowProgress.status == "completed"
                        )
                    )
                    .order_by(FollowProgress.followed_at.desc())
                    .limit(1)
                )
                last_follow_time = last_follow.scalar()
                
                if last_follow_time:
                    # Calculate minimum interval between follows for this account
                    min_interval = (settings.interval_minutes * 60) / max(settings.max_follows_per_interval, 1)
                    time_since_last = (datetime.utcnow() - last_follow_time).total_seconds()
                    
                    if time_since_last < min_interval:
                        logger.info(f"Account {account.login} needs to wait {min_interval - time_since_last:.1f}s before next follow")
                        return False

            # Skip minimum following count check since we want accounts to start following
            # if account.following_count is not None and account.following_count < settings.min_following:
            #     logger.info(f"Account {account.login} has not reached minimum following count ({account.following_count}/{settings.min_following})")
            #     return False

            # Check maximum following count
            if account.following_count is not None and account.following_count >= settings.max_following:
                logger.info(f"Account {account.login} has reached maximum following count ({account.following_count}/{settings.max_following})")
                return False

            # Check daily follow limit
            if account.daily_follows is not None and account.daily_follows >= settings.max_follows_per_day:
                logger.info(f"Account {account.login} has reached daily follow limit ({account.daily_follows}/{settings.max_follows_per_day})")
                return False

            # Account can follow
            logger.info(
                f"Account {account.login} can follow - "
                f"Following: {account.following_count}/{settings.max_following}, "
                f"Min Following: {settings.min_following}, "
                f"Daily: {account.daily_follows}/{settings.max_follows_per_day}, "
                f"Failed attempts: {account.failed_follow_attempts}"
            )
            return True

        except Exception as e:
            logger.error(f"Error checking follow limits: {str(e)}")
            return False

    async def _get_users_to_follow(
        self,
        account: Account,
        settings: FollowSettings
    ) -> Tuple[List[str], List[str]]:
        """Get next users for account to follow"""
        try:
            async with self.db_session() as session:
                # Get already followed users
                followed = await session.execute(
                    select(FollowList.username)
                    .join(FollowProgress)
                    .where(FollowProgress.account_id == account.id)
                )
                followed = set(row[0] for row in followed)

                # Get total users to follow in this interval
                total_to_follow = min(
                    settings.max_follows_per_interval,
                    settings.max_follows_per_day - (account.daily_follows or 0)
                )
                if total_to_follow <= 0:
                    logger.info(f"Account {account.login} has reached follow limits - Daily: {account.daily_follows}/{settings.max_follows_per_day}")
                    return [], []

                # Calculate how many users to follow based on ratios
                total_ratio = settings.internal_ratio + settings.external_ratio
                if total_ratio == 0:
                    logger.warning("Both internal and external ratios are 0, defaulting to 20/80")
                    internal_ratio = 0.2
                    external_ratio = 0.8
                else:
                    internal_ratio = settings.internal_ratio / total_ratio
                    external_ratio = settings.external_ratio / total_ratio

                # Calculate target numbers for this batch
                target_internal = max(1, round(total_to_follow * internal_ratio))
                target_external = max(1, round(total_to_follow * external_ratio))

                # Adjust to ensure we don't exceed daily limits
                internal_count = min(target_internal, settings.max_follows_per_day - (account.daily_follows or 0))
                external_count = min(target_external, settings.max_follows_per_day - (account.daily_follows or 0) - internal_count)

                logger.info(
                    f"Follow distribution for {account.login}:\n"
                    f"  Total to follow: {total_to_follow}\n"
                    f"  Internal ratio: {internal_ratio:.2f} ({internal_count} users)\n"
                    f"  External ratio: {external_ratio:.2f} ({external_count} users)\n"
                    f"  Current stats - Following: {account.following_count}, Daily: {account.daily_follows}"
                )

                # Get counts of available users
                internal_available = await session.scalar(
                    select(func.count(FollowList.id))
                    .where(
                        and_(
                            FollowList.list_type == ListType.INTERNAL,
                            FollowList.username != account.login,
                            ~FollowList.id.in_(
                                select(FollowProgress.follow_list_id)
                                .where(
                                    or_(
                                        FollowProgress.account_id == account.id,
                                        FollowProgress.status.in_(["in_progress", "pending"])
                                    )
                                )
                            )
                        )
                    )
                )

                external_available = await session.scalar(
                    select(func.count(FollowList.id))
                    .where(
                        and_(
                            FollowList.list_type == ListType.EXTERNAL,
                            ~FollowList.id.in_(
                                select(FollowProgress.follow_list_id)
                                .where(
                                    or_(
                                        FollowProgress.account_id == account.id,
                                        FollowProgress.status.in_(["in_progress", "pending"])
                                    )
                                )
                            )
                        )
                    )
                )

                logger.info(
                    f"Available users for {account.login}:\n"
                    f"  Internal: {internal_available} users\n"
                    f"  External: {external_available} users"
                )

                # Adjust counts based on availability
                internal_count = min(internal_count, internal_available)
                external_count = min(external_count, external_available)

                # Get internal users
                internal_query = select(FollowList).where(
                    and_(
                        FollowList.list_type == ListType.INTERNAL,
                        FollowList.username != account.login,
                        ~FollowList.id.in_(
                            select(FollowProgress.follow_list_id)
                            .where(
                                or_(
                                    FollowProgress.account_id == account.id,
                                    FollowProgress.status.in_(["in_progress", "pending"])
                                )
                            )
                        )
                    )
                ).order_by(func.random()).limit(internal_count)

                internal_result = await session.execute(internal_query)
                internal = [row.username for row in internal_result.scalars().all()]
                
                # Get external users
                external_query = select(FollowList).where(
                    and_(
                        FollowList.list_type == ListType.EXTERNAL,
                        ~FollowList.id.in_(
                            select(FollowProgress.follow_list_id)
                            .where(
                                or_(
                                    FollowProgress.account_id == account.id,
                                    FollowProgress.status.in_(["in_progress", "pending"])
                                )
                            )
                        )
                    )
                ).order_by(func.random()).limit(external_count)

                external_result = await session.execute(external_query)
                external = [row.username for row in external_result.scalars().all()]

                logger.info(
                    f"Selected users for {account.login}:\n"
                    f"  Internal ({len(internal)}): {internal}\n"
                    f"  External ({len(external)}): {external}"
                )

                # Create follow progress entries for selected users
                for username in internal + external:
                    follow_list = await session.execute(
                        select(FollowList).where(FollowList.username == username)
                    )
                    follow_list = follow_list.scalar_one_or_none()
                    if follow_list:
                        progress = FollowProgress(
                            account_id=account.id,
                            follow_list_id=follow_list.id,
                            status="pending",
                            scheduled_for=datetime.utcnow(),
                            meta_data={
                                "group": self._current_group,
                                "timestamp": datetime.utcnow().isoformat()
                            }
                        )
                        session.add(progress)
                        logger.info(f"Created follow progress entry: {account.login} -> {username}")

                return internal, external

        except Exception as e:
            logger.error(f"Error getting users to follow: {str(e)}")
            return [], []

    async def _get_attempt_count(
        self,
        session: AsyncSession,
        account_id: int,
        follow_list_id: int
    ) -> int:
        """Get number of previous follow attempts"""
        try:
            result = await session.execute(
                select(func.count(FollowProgress.id))
                .where(
                    and_(
                        FollowProgress.account_id == account_id,
                        FollowProgress.follow_list_id == follow_list_id
                    )
                )
            )
            return result.scalar() or 0
        except Exception as e:
            logger.error(f"Error getting attempt count: {str(e)}")
            return 0

    async def _process_account(self, account: Account, settings: FollowSettings) -> None:
        """Process follow operations for a single account"""
        try:
            # Check OAuth credentials
            if not all([account.consumer_key, account.consumer_secret, 
                       account.access_token, account.access_token_secret]):
                logger.error(f"Account {account.login} missing OAuth credentials")
                return

            # Check if account can follow more users
            if not await self._can_account_follow(account, settings):
                return

            # Get next users to follow
            internal_users, external_users = await self._get_users_to_follow(account, settings)
            users_to_follow = internal_users + external_users

            if not users_to_follow:
                logger.info(f"No users to follow for account {account.login}")
                return

            # Follow each user
            for username in users_to_follow:
                if not self._running:
                    break
                    
                success = await self._follow_user(account, username)
                if not success:
                    break  # Stop on first failure
                    
                # Wait between follows
                await asyncio.sleep(settings.interval_minutes * 60 / settings.max_follows_per_interval)

        except Exception as e:
            logger.error(f"Error processing account {account.login}: {str(e)}")

    async def _follow_user(self, account: Account, username: str) -> bool:
        """Follow a user and record progress"""
        client = None
        try:
            # Initialize client with OAuth credentials
            # Initialize client with OAuth credentials
            client = TwitterClient(
                account_no=account.account_no,
                auth_token=account.auth_token,
                ct0=account.ct0,
                proxy_config=account.get_proxy_config(),
                user_agent=account.user_agent,
                consumer_key=account.consumer_key,
                consumer_secret=account.consumer_secret,
                bearer_token=account.bearer_token,  # Add bearer token
                access_token=account.access_token,
                access_token_secret=account.access_token_secret
            )

            # Log detailed attempt info
            group_info = f"Group {self._current_group + 1}"
            start_time = datetime.utcnow()
            logger.info(
                f"[{group_info}] Follow attempt:"
                f"\n  Account: {account.login}"
                f"\n  Target: {username}"
                f"\n  Daily follows: {account.daily_follows or 0}/{self._settings.max_follows_per_day}"
                f"\n  Following count: {account.following_count or 0}/{self._settings.max_following}"
                f"\n  Last followed: {account.last_followed_at}"
            )

            # Get follow list entry first
            follow_list = None
            async with self.db_session() as session:
                follow_list_result = await session.execute(
                    select(FollowList).where(FollowList.username == username)
                )
                follow_list = follow_list_result.scalar_one_or_none()
                
            if not follow_list:
                logger.error(f"[{group_info}] Follow list entry not found for {username}")
                return False

            # Create in_progress record
            async with self.db_session() as session:
                async with session.begin():
                    progress = FollowProgress(
                        account_id=account.id,
                        follow_list_id=follow_list.id,
                        status="in_progress",
                        started_at=start_time,
                        scheduled_for=start_time,
                        meta_data={
                            "group": self._current_group,
                            "timestamp": start_time.isoformat()
                        }
                    )
                    session.add(progress)
                    await session.commit()

            # Follow user using Twitter API
            result = await client.follow_user(username)
            success = result.get("success", False)
            error = result.get("error")

            # Log detailed result
            now = datetime.utcnow()
            duration = (now - start_time).total_seconds()
            if success:
                logger.info(
                    f"[{group_info}] ✓ Follow success:"
                    f"\n  Account: {account.login}"
                    f"\n  Target: {username}"
                    f"\n  Duration: {duration:.2f}s"
                )
            else:
                logger.error(
                    f"[{group_info}] ✗ Follow failed:"
                    f"\n  Account: {account.login}"
                    f"\n  Target: {username}"
                    f"\n  Error: {error}"
                    f"\n  Duration: {duration:.2f}s"
                )

            # Get attempt count
            attempt_count = await self._get_attempt_count(session, account.id, follow_list.id)

            # Calculate next scheduled follow time (15 minutes from now)
            next_follow_time = now + timedelta(minutes=15)
            
            # Get all pending follows for this account
            async with self.db_session() as session:
                pending_follows = await session.execute(
                    select(FollowList)
                    .join(FollowProgress)
                    .where(
                        and_(
                            FollowProgress.account_id == account.id,
                            FollowProgress.status == "pending"
                        )
                    )
                    .order_by(FollowProgress.scheduled_for.asc())
                )
                pending_follows = pending_follows.scalars().all()
                
                # Schedule next 24 hours of follows with proper ratio distribution
                schedule_until = now + timedelta(hours=24)
                follow_time = next_follow_time
                
                # Get all available users
                available_internal = await session.execute(
                    select(FollowList)
                    .where(
                        and_(
                            FollowList.list_type == ListType.INTERNAL,
                            ~FollowList.id.in_(
                                select(FollowProgress.follow_list_id)
                                .where(FollowProgress.account_id == account.id)
                            )
                        )
                    )
                    .order_by(func.random())
                )
                available_internal = available_internal.scalars().all()
                
                available_external = await session.execute(
                    select(FollowList)
                    .where(
                        and_(
                            FollowList.list_type == ListType.EXTERNAL,
                            ~FollowList.id.in_(
                                select(FollowProgress.follow_list_id)
                                .where(FollowProgress.account_id == account.id)
                            )
                        )
                    )
                    .order_by(func.random())
                )
                available_external = available_external.scalars().all()
                
                # Calculate how many of each type to schedule
                total_to_schedule = min(
                    settings.max_follows_per_day - (account.daily_follows or 0),
                    len(available_internal) + len(available_external)
                )
                internal_to_schedule = round(total_to_schedule * internal_ratio)
                external_to_schedule = total_to_schedule - internal_to_schedule
                
                # Create mixed schedule
                internal_idx = 0
                external_idx = 0
                scheduled_count = 0
                
                while follow_time < schedule_until and scheduled_count < total_to_schedule:
                    # Randomly choose internal or external based on ratios
                    if (internal_idx < len(available_internal) and 
                        (external_idx >= len(available_external) or 
                         internal_idx < internal_to_schedule and 
                         (external_idx >= external_to_schedule or 
                          func.random() < internal_ratio))):
                        follow = available_internal[internal_idx]
                        internal_idx += 1
                    elif external_idx < len(available_external):
                        follow = available_external[external_idx]
                        external_idx += 1
                    else:
                        break
                        
                    next_progress = FollowProgress(
                        account_id=account.id,
                        follow_list_id=follow.id,
                        status="pending",
                        scheduled_for=follow_time,
                        meta_data={
                            "group": self._current_group,
                            "scheduled_timestamp": follow_time.isoformat(),
                            "type": "internal" if follow.list_type == ListType.INTERNAL else "external"
                        }
                    )
                    session.add(next_progress)
                    follow_time += timedelta(minutes=15)
                    scheduled_count += 1
                    
                logger.info(
                    f"Scheduled follows for {account.login}:\n"
                    f"  Total scheduled: {scheduled_count}\n"
                    f"  Internal: {internal_idx}\n"
                    f"  External: {external_idx}\n"
                    f"  Until: {schedule_until}"
                )
                
                await session.commit()

            # Update progress and metrics
            async with self.db_session() as session:
                async with session.begin():
                        # Update progress record
                        await session.execute(
                            update(FollowProgress)
                            .where(
                                and_(
                                    FollowProgress.account_id == account.id,
                                    FollowProgress.follow_list_id == follow_list.id,
                                    FollowProgress.status == "in_progress"
                                )
                            )
                            .values(
                                status="completed" if success else "failed",
                                followed_at=now if success else None,
                                error_message=error,
                                meta_data={
                                    "group": self._current_group,
                                    "duration_ms": int(duration * 1000),
                                    "account_following_count": account.following_count or 0,
                                    "attempt_count": attempt_count + 1,
                                    "success": success,
                                    "timestamp": now.isoformat(),
                                    "next_follow": next_follow_time.isoformat()
                                }
                            )
                        )

                        # Get fresh account instance
                        account_fresh = await session.get(Account, account.id)
                        if not account_fresh:
                            logger.error(f"Could not find account {account.login} in database")
                            return False

                        # Update account metrics
                        if success:
                            account_fresh.following_count = (account_fresh.following_count or 0) + 1
                            account_fresh.last_followed_at = now
                            account_fresh.daily_follows = (account_fresh.daily_follows or 0) + 1
                            account_fresh.total_follows = (account_fresh.total_follows or 0) + 1
                            
                            logger.info(
                                f"Updated metrics for {account_fresh.login}: "
                                f"following={account_fresh.following_count}, "
                                f"daily={account_fresh.daily_follows}, "
                                f"total={account_fresh.total_follows}"
                            )
                            
                            # Check follow limits
                            if account_fresh.daily_follows >= self._settings.max_follows_per_day:
                                account_fresh.is_active = False
                                logger.warning(f"Account {account_fresh.login} reached daily follow limit")
                            elif account_fresh.following_count >= self._settings.max_following:
                                account_fresh.is_active = False
                                logger.warning(f"Account {account_fresh.login} reached total follow limit")
                        else:
                            # Track failed attempts and rate limits
                            account_fresh.failed_follow_attempts = (account_fresh.failed_follow_attempts or 0) + 1
                            
                            if error and "rate limit" in str(error).lower():
                                rate_limit_time = now + timedelta(minutes=15)
                                account_fresh.rate_limit_until = rate_limit_time
                                account_fresh.is_active = False
                                logger.warning(f"Account {account_fresh.login} rate limited until {rate_limit_time}")
                            elif account_fresh.failed_follow_attempts >= 5:
                                account_fresh.is_active = False
                                logger.warning(f"Account {account_fresh.login} deactivated due to too many failed attempts")

                        # Create next scheduled follow entry if successful
                        if success:
                            next_users = await self._get_users_to_follow(account_fresh, self._settings)
                            if next_users[0] or next_users[1]:  # If there are more users to follow
                                next_username = (next_users[0] + next_users[1])[0]
                                next_follow_list = await session.execute(
                                    select(FollowList).where(FollowList.username == next_username)
                                )
                                next_follow_list = next_follow_list.scalar_one_or_none()
                                if next_follow_list:
                                    next_progress = FollowProgress(
                                        account_id=account.id,
                                        follow_list_id=next_follow_list.id,
                                        status="pending",
                                        scheduled_for=next_follow_time,
                                        meta_data={
                                            "group": self._current_group,
                                            "scheduled_timestamp": next_follow_time.isoformat()
                                        }
                                    )
                                    session.add(next_progress)

                        await session.commit()

                        # Log final status
                        logger.info(
                            f"[{group_info}] Account {account.login} - "
                            f"Following: {account.following_count}, "
                            f"Status: {'✓' if success else '✗'}, "
                            f"Duration: {duration * 1000:.0f}ms"
                        )

                        return success
        except Exception as e:
            logger.error(f"Error in follow process: {str(e)}")
            return False
        finally:
            if client:
                try:
                    await client.close()
                except:
                    pass
