import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.account import Account, ValidationState
from ..models.settings import SystemSettings
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

class WorkerPool:
    def __init__(self, rate_limiter: RateLimiter):
        self.rate_limiter = rate_limiter
        self.settings = None
        self._active_workers = set()

    async def load_settings(self, session: AsyncSession) -> None:
        """Load worker pool settings from database"""
        result = await session.execute(select(SystemSettings).limit(1))
        settings = result.scalar_one_or_none()
        
        if not settings:
            settings = SystemSettings()
            session.add(settings)
        
        self.settings = {
            "max_workers": settings.max_concurrent_workers,
            "requests_per_worker": settings.max_requests_per_worker,
            "request_interval": settings.request_interval
        }

    async def get_available_workers(
        self,
        session: AsyncSession,
        endpoint: str,
        count: int
    ) -> List[Account]:
        """Get available workers with proper locking and health checks"""
        if not self.settings:
            await self.load_settings(session)

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

        # Filter and validate workers
        available_accounts = []
        for account in all_accounts:
            if await self._is_worker_available(session, account, endpoint):
                available_accounts.append(account)
                account.last_task_time = datetime.utcnow()
                session.add(account)
                if len(available_accounts) >= count:
                    break

        return available_accounts

    async def _is_worker_available(
        self,
        session: AsyncSession,
        worker: Account,
        endpoint: str
    ) -> bool:
        """Check if worker is available and healthy"""
        # Check rate limits
        can_use, _, _ = await self._check_rate_limits(session, worker, endpoint)
        if not can_use:
            return False

        # Check health status
        if not await self._check_worker_health(session, worker):
            return False

        # Check if worker is already active
        if worker in self._active_workers:
            return False

        return True

    async def _check_rate_limits(
        self,
        session: AsyncSession,
        worker: Account,
        endpoint: str
    ) -> Tuple[bool, Optional[str], Optional[datetime]]:
        """Check worker rate limits"""
        try:
            # Action-specific rate limits
            if endpoint in ["follow_user", "send_dm"]:
                limits = {
                    "follow_user": {"15min": 2, "24h": 20},
                    "send_dm": {"15min": 1, "24h": 24}
                }
                endpoint_limits = limits.get(endpoint, {"15min": 30, "24h": 300})
                
                can_use_15min = await self.rate_limiter.check_rate_limit(
                    account_id=worker.id,
                    action_type=endpoint,
                    window='15min',
                    limit=endpoint_limits["15min"]
                )
                
                can_use_24h = await self.rate_limiter.check_rate_limit(
                    account_id=worker.id,
                    action_type=endpoint,
                    window='24h',
                    limit=endpoint_limits["24h"]
                )
            else:
                # Standard worker limits
                can_use_15min = await self.rate_limiter.check_rate_limit(
                    account_id=worker.id,
                    action_type=endpoint,
                    window='15min',
                    limit=self.settings["requests_per_worker"]
                )
                
                can_use_24h = await self.rate_limiter.check_rate_limit(
                    account_id=worker.id,
                    action_type=endpoint,
                    window='24h',
                    limit=int(self.settings["requests_per_worker"] * (24 * 60 / self.settings["request_interval"]))
                )
            
            if not can_use_15min:
                return False, "15-minute rate limit exceeded", None
            if not can_use_24h:
                return False, "24-hour rate limit exceeded", None
            return True, None, None
            
        except Exception as e:
            logger.error(f"Error checking rate limits: {str(e)}")
            return False, str(e), None

    async def _check_worker_health(
        self,
        session: AsyncSession,
        worker: Account
    ) -> bool:
        """Check if worker is healthy"""
        # Check last successful task completion
        if worker.last_task_time:
            time_since_last = datetime.utcnow() - worker.last_task_time
            if time_since_last > timedelta(minutes=30):  # Increased timeout to 30 minutes
                logger.warning(f"Worker {worker.account_no} has not completed tasks in 30 minutes")
                return False

        # Check required credentials
        required_fields = ["auth_token", "ct0"]
        for field in required_fields:
            if not getattr(worker, field):
                logger.warning(f"Worker {worker.account_no} missing {field}")
                return False

        return True

    def activate_worker(self, worker: Account) -> bool:
        """Activate a worker"""
        if len(self._active_workers) < self.settings["max_workers"]:
            self._active_workers.add(worker)
            return True
        return False

    def deactivate_worker(self, worker: Account) -> None:
        """Deactivate a worker"""
        self._active_workers.discard(worker)

    async def rotate_workers(self, session: AsyncSession) -> None:
        """Rotate workers based on health and rate limits"""
        # Deactivate unhealthy workers
        for worker in list(self._active_workers):
            if not await self._check_worker_health(session, worker):
                self.deactivate_worker(worker)

        # Get all available workers
        stmt = select(Account).where(
            and_(
                Account.act_type == 'worker',
                Account.is_worker == True,
                Account.deleted_at.is_(None),
                or_(
                    Account.validation_in_progress == ValidationState.COMPLETED,
                    Account.validation_in_progress == ValidationState.PENDING
                )
            )
        ).order_by(
            Account.current_15min_requests.asc(),
            Account.total_tasks_completed.asc()
        )
        
        result = await session.execute(stmt)
        available_workers = result.scalars().all()

        # Activate new workers up to max limit
        for worker in available_workers:
            if len(self._active_workers) >= self.settings["max_workers"]:
                break
            if worker not in self._active_workers:
                if await self._is_worker_available(session, worker, "like_tweet"):  # Use generic endpoint for health check
                    self.activate_worker(worker)
