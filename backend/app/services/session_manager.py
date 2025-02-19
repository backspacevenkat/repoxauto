from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from typing import AsyncGenerator, Callable
import logging

logger = logging.getLogger(__name__)

class SessionManager:
    def __init__(self, session_maker: Callable[[], AsyncSession]):
        self.session_maker = session_maker

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Provide a transactional session scope."""
        session = self.session_maker()
        try:
            yield session
        finally:
            await session.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession, None]:
        """Provide a managed transaction scope."""
        async with self.session() as session:
            async with session.begin():
                try:
                    yield session
                except Exception as e:
                    logger.error(f"Transaction error: {str(e)}")
                    await session.rollback()
                    raise

    @asynccontextmanager
    async def retryable_transaction(self, max_retries: int = 3) -> AsyncGenerator[AsyncSession, None]:
        """Provide a transaction scope with retries for transient failures."""
        retries = 0
        while True:
            try:
                async with self.transaction() as session:
                    yield session
                break
            except Exception as e:
                retries += 1
                if retries >= max_retries:
                    logger.error(f"Max retries ({max_retries}) exceeded: {str(e)}")
                    raise
                logger.warning(f"Retrying transaction (attempt {retries}/{max_retries}): {str(e)}")
