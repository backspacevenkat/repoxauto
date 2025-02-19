import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy import event, text, select
from sqlalchemy.schema import CreateTable
from contextlib import asynccontextmanager
import os
import logging
from typing import AsyncGenerator, Optional, Literal
import asyncio
from datetime import datetime
import json
import aiofiles
from fastapi import Depends, HTTPException, status
import shutil
import enum

# Import Base from models.base instead
from .models.base import Base

# Import Account model
from .models.account import Account, ValidationState

# Configure logging
logger = logging.getLogger(__name__)

# Get the absolute path to the backend directory
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Create the database directory if it doesn't exist
DB_PATH = os.path.join(BACKEND_DIR, "app.db")
DB_DIR = os.path.dirname(DB_PATH)
os.makedirs(DB_DIR, exist_ok=True)

# Database URLs - migrating fully to PostgreSQL for now
DATABASE_URL = "postgresql+asyncpg://neondb_owner:npg_4GK5QbBnqzdk@ep-lively-darkness-a6zoh3mw-pooler.us-west-2.aws.neon.tech/neondb?ssl=true"

# Sync URLs for migrations - using same PostgreSQL instance
SYNC_DATABASE_URL = "postgresql://neondb_owner:npg_4GK5QbBnqzdk@ep-lively-darkness-a6zoh3mw-pooler.us-west-2.aws.neon.tech/neondb?ssl=true"

logger.info(f"Database path: {DB_PATH}")

class DatabaseManager:
    """Manages database connections and operations"""
    def __init__(self):
        self.BACKUP_DIR = "backups/database"
        os.makedirs(self.BACKUP_DIR, exist_ok=True)

        self.engine = None
        self.async_session = None
        self.db_type = None
        self.is_connected = False
        self.last_backup = None
        self.errors = 0

    async def test_connection(self, url: str) -> bool:
        """Test database connection"""
        try:
            # Create temporary engine for testing
            test_engine = create_async_engine(url, echo=False)
            async with test_engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
                
            await test_engine.dispose()
            return True
        except Exception as e:
            logger.error(f"Database connection test failed for {url}: {e}")
            return False

    def configure_engine(self, url: str, is_sqlite: bool = False):
        """Configure database engine"""
        try:
            engine_args = {
                "echo": False,
                "future": True
            }
            
            if is_sqlite:
                # Ensure SQLite connection parameters
                engine_args.update({
                    "connect_args": {
                        "check_same_thread": False
                    }
                })
            else:
                engine_args.update({
                    "pool_size": 20,
                    "max_overflow": 10,
                    "pool_timeout": 30,
                    "pool_pre_ping": True
                })
            
            self.engine = create_async_engine(url, **engine_args)
            if is_sqlite:
                from sqlalchemy import event
                @event.listens_for(self.engine.sync_engine, "connect")
                def set_sqlite_pragma(dbapi_connection, connection_record):
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.close()
            self.db_type = "sqlite" if is_sqlite else "postgresql"
            
            # Create session factory with configured options
            session_factory = async_sessionmaker(
                bind=self.engine.execution_options(
                    populate_existing=True,
                    raiseload=False
                ),
                class_=AsyncSession,
                expire_on_commit=False,
                future=True
            )
            
            # Create session factory function
            self.async_session = lambda: session_factory()
            
            self.is_connected = True
            logger.info(f"Successfully configured {self.db_type} database engine")
            return True
        except Exception as e:
            logger.error(f"Error configuring database engine: {e}")
            return False

    async def initialize(self):
        """Initialize database connection"""
        try:
            # Using PostgreSQL exclusively
            if await self.test_connection(DATABASE_URL):
                success = self.configure_engine(DATABASE_URL)
                if success:
                    self.is_connected = True
                    return True
            
            raise Exception("Failed to connect to PostgreSQL database")
            
        except Exception as e:
            logger.error(f"Database initialization failed: {str(e)}")
            self.is_connected = False
            return False

    async def create_backup(self):
        """Create a backup of the database and all related data"""
        try:
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            backup_path = os.path.join(self.BACKUP_DIR, f'backup_{timestamp}')
            os.makedirs(backup_path, exist_ok=True)

            # Backup database tables
            async with self.async_session() as session:
                # Get all tables
                for table in Base.metadata.sorted_tables:
                    try:
                        # Handle follow_settings table specially
                        if table.name == "follow_settings":
                            # Get the actual model class
                            model_class = None
                            for m in Base.registry.mappers:
                                if m.class_.__table__.name == table.name:
                                    model_class = m.class_
                                    break
                            
                            if model_class:
                                stmt = select(model_class).execution_options(populate_existing=True)
                                result = await session.execute(stmt)
                                rows = result.unique().scalars().all()
                            else:
                                # Fallback to raw table select
                                result = await session.execute(
                                    select(table).execution_options(populate_existing=True)
                                )
                                rows = result.mappings().all()
                        else:
                            # Normal table handling
                            result = await session.execute(
                                select(table).execution_options(populate_existing=True)
                            )
                            rows = result.unique().scalars().all()
                        
                        # Save table data to JSON
                        table_data = []
                        for row in rows:
                            try:
                                row_dict = {}
                                for column in table.columns:
                                    try:
                                        # Handle different row types
                                        if hasattr(row, '__table__'):
                                            # SQLAlchemy model instance
                                            value = getattr(row, column.name)
                                        elif hasattr(row, '_mapping'):
                                            # Row mapping
                                            value = row._mapping[column.name]
                                        elif isinstance(row, dict):
                                            # Dictionary
                                            value = row[column.name]
                                        else:
                                            # KeyedTuple or other result type
                                            value = getattr(row, column.name, None)
                                            
                                        # Convert values to JSON-serializable format
                                        if isinstance(value, datetime):
                                            value = value.isoformat()
                                        elif hasattr(value, 'value'):  # Handle any enum-like objects
                                            value = value.value
                                        elif isinstance(value, (int, float, str, bool, type(None))):
                                            value = value
                                        else:
                                            try:
                                                value = str(value)
                                            except:
                                                value = None
                                        
                                        row_dict[column.name] = value
                                    except Exception as e:
                                        logger.warning(f"Could not access {column.name} in {table.name}: {e}")
                                        continue
                                table_data.append(row_dict)
                            except Exception as e:
                                logger.warning(f"Error processing row in table {table.name}: {e}")
                                continue
                        
                        # Write to backup file
                        async with aiofiles.open(f"{backup_path}/{table.name}.json", 'w') as f:
                            await f.write(json.dumps(table_data, indent=2))
                        
                        logger.info(f"Successfully backed up table {table.name}")
                    except Exception as e:
                        logger.warning(f"Error backing up table {table.name}: {e}")
                        continue

            # Backup account states
            if os.path.exists('account_states'):
                shutil.copytree('account_states', f'{backup_path}/account_states', dirs_exist_ok=True)

            self.last_backup = datetime.utcnow()
            logger.info(f"Created backup at {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"Error creating backup: {e}")
            raise

    async def restore_from_backup(self, backup_path: str = None):
        """Restore database from the latest backup or specified backup"""
        try:
            # Find latest backup if not specified
            if not backup_path:
                backups = [d for d in os.listdir(self.BACKUP_DIR) if os.path.isdir(os.path.join(self.BACKUP_DIR, d))]
                if not backups:
                    logger.warning("No backups found to restore from")
                    return
                latest_backup = sorted(backups)[-1]
                backup_path = os.path.join(self.BACKUP_DIR, latest_backup)

            logger.info(f"Restoring from backup: {backup_path}")

            async with self.async_session() as session:
                # Restore each table
                for table in Base.metadata.sorted_tables:
                    try:
                        backup_file = f"{backup_path}/{table.name}.json"
                        if not os.path.exists(backup_file):
                            continue

                        async with aiofiles.open(backup_file, 'r') as f:
                            content = await f.read()
                            rows = json.loads(content)

                        for row_data in rows:
                            # Convert ISO format strings back to datetime
                            for key, value in row_data.items():
                                if isinstance(value, str) and 'T' in value:
                                    try:
                                        row_data[key] = datetime.fromisoformat(value)
                                    except ValueError:
                                        pass

                            try:
                                # Get the actual model class, not just the table
                                model_class = None
                                for m in Base.registry.mappers:
                                    if m.class_.__table__.name == table.name:
                                        model_class = m.class_
                                        break
                                
                                if model_class:
                                    # Create model instance and add to session
                                    instance = model_class(**row_data)
                                    session.add(instance)
                                else:
                                    # Fallback to raw table insert if no model found
                                    stmt = table.insert().values(**row_data)
                                    await session.execute(stmt)

                            except Exception as e:
                                logger.warning(f"Error restoring row in table {table.name}: {e}")
                                continue
                        
                        try:
                            await session.commit()
                            logger.info(f"Restored table: {table.name}")
                        except Exception as e:
                            logger.error(f"Error committing table {table.name}: {e}")
                            await session.rollback()

                    except Exception as e:
                        logger.error(f"Error restoring table {table.name}: {e}")
                        await session.rollback()

            # Restore account states
            account_states_backup = f'{backup_path}/account_states'
            if os.path.exists(account_states_backup):
                if os.path.exists('account_states'):
                    shutil.rmtree('account_states')
                shutil.copytree(account_states_backup, 'account_states')

            logger.info("Database restore completed")
        except Exception as e:
            logger.error(f"Error restoring from backup: {e}")
            raise

    async def cleanup(self):
        """Cleanup database connections and create backup"""
        try:
            # Create backup before cleanup
            await self.create_backup()
            
            # Close all connections in the pool
            if self.engine:
                await self.engine.dispose()
            self.is_connected = False
            logger.info("Database connections closed")
        except Exception as e:
            logger.error(f"Error cleaning up database: {e}")
            raise

    def get_stats(self):
        """Get current database statistics"""
        return {
            "type": self.db_type,
            "connected": self.is_connected,
            "errors": self.errors,
            "last_backup": self.last_backup.isoformat() if self.last_backup else None
        }

# Create global database manager instance
db_manager = DatabaseManager()

# Export session factory for backward compatibility
async_session = db_manager.async_session

async def init_db():
    """Initialize database and create tables"""
    try:
        # Test database connection first
        async with db_manager.async_session() as session:
            try:
                # Try a simple query
                await session.execute(text("SELECT 1"))
                logger.info("Database connection test successful")
                
                # Set connection status
                db_manager.is_connected = True
                
            except Exception as e:
                logger.error(f"Database connection test failed: {str(e)}")
                db_manager.is_connected = False
                raise

        # Create tables
        async with db_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created/verified")

        # Check if database is empty
        async with db_manager.async_session() as session:
            result = await session.execute(select(Account).limit(1))
            has_data = result.scalar_one_or_none() is not None
            logger.info(f"Database has existing data: {has_data}")

            if not has_data:
                logger.info("Database is empty, attempting to restore from backup")
                await db_manager.restore_from_backup()
            else:
                logger.info("Database already contains data, skipping restore")

    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}", exc_info=True)
        db_manager.is_connected = False
        raise

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions with async context management"""
    if not db_manager.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection not available"
        )

    session = db_manager.async_session()
    try:
        yield session
        
        # Only commit if there are pending changes
        if session.in_transaction():
            await session.commit()
            
    except Exception as e:
        if session.in_transaction():
            await session.rollback()
        if isinstance(e, HTTPException):
            raise
        else:
            error_msg = str(e)
            logger.error(f"Database session error: {error_msg}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Database error: {error_msg}"
            ) from e
    finally:
        await session.close()

async def safe_commit(session: AsyncSession) -> bool:
    """Safely commit changes with error handling"""
    try:
        await session.commit()
        return True
    except Exception as e:
        await session.rollback()
        logger.error(f"Error during commit: {str(e)}")
        return False

db_dependency = Depends(get_db)
get_session = get_db  # For backward compatibility

async def monitor_db_health():
    """Monitor database health and create periodic backups"""
    while True:
        try:
            # Health check
            if not await db_manager.test_connection(DATABASE_URL):
                logger.debug("PostgreSQL connection lost, attempting to reconnect...")
                await db_manager.initialize()

            # Create backup every 6 hours
            if (not db_manager.last_backup or 
                (datetime.utcnow() - db_manager.last_backup).total_seconds() > 21600):
                await db_manager.create_backup()

        except Exception as e:
            if "Connection refused" in str(e):
                logger.debug(f"Database health check failed: {e}")
            else:
                logger.error(f"Database health check failed: {e}")
                db_manager.errors += 1
        finally:
            await asyncio.sleep(60)  # Check every minute

# Export Base and other database components
__all__ = ['Base', 'db_manager', 'get_db']
