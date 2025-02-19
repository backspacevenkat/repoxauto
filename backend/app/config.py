from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from redis.asyncio import Redis
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class DatabaseConfig:
    def __init__(self, db_url: str):
        self.engine = create_async_engine(db_url, echo=True)
        self.async_session = sessionmaker(
            self.engine, 
            class_=AsyncSession, 
            expire_on_commit=False
        )

    async def get_session(self) -> AsyncSession:
        async with self.async_session() as session:
            try:
                yield session
            except Exception as e:
                await session.rollback()
                raise
            finally:
                await session.close()

class RedisConfig:
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._redis: Optional[Redis] = None

    async def get_redis(self):
        if not self._redis:
            try:
                self._redis = Redis.from_url(self.redis_url, decode_responses=True)
                await self._redis.ping()
            except Exception as e:
                logger.error(f"Redis connection failed: {e}")
                self._redis = None
        return self._redis

    async def close(self):
        if self._redis:
            await self._redis.close()
