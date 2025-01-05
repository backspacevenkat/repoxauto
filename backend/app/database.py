from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy import event, text
from contextlib import asynccontextmanager
import os
import logging
from typing import AsyncGenerator
import asyncio
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

# Get database URL from environment or use default
# Get absolute path to database file
DB_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "xauto.db"))
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{DB_FILE}"
)
logger.info(f"Using database at: {DB_FILE}")

# Database configuration
DB_POOL_SIZE = 20
DB_MAX_OVERFLOW = 10
DB_POOL_TIMEOUT = 30
DB_ECHO = False

# Create engine with SQLite-specific settings
engine = create_async_engine(
    DATABASE_URL,
    echo=DB_ECHO,
    future=True,
    connect_args={
        "timeout": 60,  # SQLite timeout in seconds
        "check_same_thread": False,  # Required for SQLite
    } if DATABASE_URL.startswith("sqlite") else {},
    execution_options={
        "isolation_level": "SERIALIZABLE"
    } if DATABASE_URL.startswith("sqlite") else {}
)

# Configure SQLite settings
async def configure_sqlite():
    if DATABASE_URL.startswith("sqlite"):
        async with engine.begin() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA busy_timeout=60000"))
            await conn.execute(text("PRAGMA synchronous=NORMAL"))
            await conn.execute(text("PRAGMA temp_store=MEMORY"))

# Create session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# Create declarative base
Base = declarative_base()

# Connection pool monitoring (only for non-SQLite databases)
if not DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "checkout")
    def receive_checkout(dbapi_connection, connection_record, connection_proxy):
        """Log when a connection is checked out from the pool."""
        logger.debug("Connection checked out")

    @event.listens_for(engine.sync_engine, "checkin")
    def receive_checkin(dbapi_connection, connection_record):
        """Log when a connection is checked back into the pool."""
        logger.debug("Connection checked in")

async def init_db(force_reset: bool = False):
    """Initialize the database by creating all tables."""
    try:
        db_file = "backend/xauto.db"
        
        # Handle database reset if requested
        if force_reset and os.path.exists(db_file):
            try:
                os.remove(db_file)
                logger.info("Removed existing database file")
            except Exception as e:
                logger.error(f"Error removing database file: {e}")
                raise

        # Create database directory if it doesn't exist
        os.makedirs(os.path.dirname(db_file), exist_ok=True)

        # Configure SQLite settings first
        await configure_sqlite()

        async with engine.begin() as conn:
            # Drop all tables first
            await conn.run_sync(Base.metadata.drop_all)
            # Create all tables
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Created all database tables")

        logger.info("Database initialization complete")

    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise

@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session with proper error handling and cleanup."""
    session = async_session()
    try:
        yield session
    except Exception as e:
        logger.error(f"Database session error: {e}")
        await session.rollback()
        raise
    finally:
        await session.close()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions."""
    async with get_session() as session:
        yield session

async def cleanup_db():
    """Cleanup database connections."""
    try:
        # Close all connections in the pool
        await engine.dispose()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error(f"Error cleaning up database: {e}")
        raise

class DatabaseStats:
    """Class to track database statistics."""
    def __init__(self):
        self.start_time = datetime.utcnow()
        self.total_connections = 0
        self.active_connections = 0
        self.errors = 0

    def to_dict(self):
        """Convert stats to dictionary."""
        return {
            "uptime": str(datetime.utcnow() - self.start_time),
            "total_connections": self.total_connections,
            "active_connections": self.active_connections,
            "errors": self.errors,
            "pool_size": DB_POOL_SIZE,
            "max_overflow": DB_MAX_OVERFLOW
        }

# Initialize database stats
db_stats = DatabaseStats()

async def get_db_stats():
    """Get current database statistics."""
    try:
        db_stats.active_connections = 0 if DATABASE_URL.startswith("sqlite") else engine.sync_engine.pool.checkedout()
        return db_stats.to_dict()
    except Exception as e:
        logger.error(f"Error getting database stats: {e}")
        return None

# Background task to monitor database health
async def monitor_db_health():
    """Monitor database health in the background."""
    while True:
        try:
            async with get_session() as session:
                # Simple query to test connection
                await session.execute("SELECT 1")
            logger.debug("Database health check passed")
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            db_stats.errors += 1
        finally:
            await asyncio.sleep(60)  # Check every minute
