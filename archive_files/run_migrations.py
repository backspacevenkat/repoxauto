#!/usr/bin/env python3
import asyncio
import logging
import os
from alembic import command
from alembic.config import Config
from datetime import datetime
from sqlalchemy import select
from backend.app.database import engine, async_session
from backend.app.models.follow_settings import FollowSettings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

async def run_migrations():
    try:
        # Initialize database without creating tables
        logger.info("Initializing database...")
        await engine.dispose()
        logger.info("Closed existing database connections")

        # Run Alembic migrations
        logger.info("Running migrations...")
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        
        # Create default settings after migrations
        async with async_session() as session:
            async with session.begin():
                try:
                    existing = await session.execute(select(FollowSettings))
                    if not existing.scalar_one_or_none():
                        settings = FollowSettings(
                            max_follows_per_interval=1,
                            interval_minutes=16,
                            max_follows_per_day=30,
                            internal_ratio=5,
                            external_ratio=25,
                            max_following=400,
                            schedule_groups=3,
                            schedule_hours=8,
                            is_active=False,
                            updated_at=datetime.utcnow(),
                            created_at=datetime.utcnow()
                        )
                        session.add(settings)
                        await session.commit()
                        logger.info("Created default follow settings")
                except Exception as e:
                    logger.error(f"Error creating default settings: {e}")
                    await session.rollback()
                    raise

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
