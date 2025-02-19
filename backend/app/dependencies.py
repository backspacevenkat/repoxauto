from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import AsyncGenerator
from .config import DatabaseConfig, RedisConfig
import logging
import os

logger = logging.getLogger(__name__)

# Get database credentials from environment
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "xauto")

# Get Redis credentials from environment
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")

# Initialize configurations
db_config = DatabaseConfig(f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}")
redis_config = RedisConfig(f"redis://{REDIS_HOST}:{REDIS_PORT}")

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import AsyncGenerator, Dict
from .config import DatabaseConfig, RedisConfig
import logging
import os

logger = logging.getLogger(__name__)

# Get database credentials from environment
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "xauto")

# Get Redis credentials from environment
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")

# Initialize configurations
db_config = DatabaseConfig(f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}")
redis_config = RedisConfig(f"redis://{REDIS_HOST}:{REDIS_PORT}")

async def get_current_user() -> Dict:
    """Get current user info - hardcoded for now"""
    # TODO: Implement proper user authentication
    return {"id": 1, "username": "admin"}

from .database import get_db

import redis as redislib  # Rename to avoid conflict

async def get_redis(request: Request) -> AsyncGenerator[redislib.Redis, None]:
    """Redis dependency providing connection from pool"""
    try:
        # Initialize connection pool if it doesn't exist
        if not hasattr(request.app.state, 'redis_pool'):
            request.app.state.redis_pool = redislib.Redis.from_url(
                redis_config.url,
                decode_responses=True,
                max_connections=20,
                socket_connect_timeout=5,
                socket_keepalive=True
            )

        # Get connection from pool
        redis_conn: redislib.Redis = request.app.state.redis_pool
        
        # Test connection
        if not redis_conn.ping():
            raise ConnectionError("Redis ping failed")

        yield redis_conn

    except Exception as e:
        logger.error(f"Redis connection error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Redis connection error"
        )
