#!/usr/bin/env python3
import asyncio
import logging
from alembic import command
from alembic.config import Config
from backend.app.database import init_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

async def run_migrations():
    try:
        # Initialize database
        logger.info("Initializing database...")
        await init_db()

        # Run Alembic migrations
        logger.info("Running migrations...")
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        
        logger.info("Migrations completed successfully!")

    except Exception as e:
        logger.error(f"Error during migrations: {str(e)}")
        raise

if __name__ == "__main__":
    try:
        # Create and run event loop
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_migrations())
    except KeyboardInterrupt:
        logger.info("Migration interrupted by user")
    except Exception as e:
        logger.error(f"Migration failed: {str(e)}")
        exit(1)
    finally:
        loop.close()
