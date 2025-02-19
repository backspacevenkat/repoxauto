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
