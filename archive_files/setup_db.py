#!/usr/bin/env python3
import asyncio
import logging
from datetime import datetime
from sqlalchemy import text, select

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

async def setup_database():
    try:
        from backend.app.database import engine, async_session, Base
        from backend.app.models.follow_settings import FollowSettings
        from backend.app.models.follow_list import FollowList, FollowProgress
        from backend.app.models.account import Account
        from backend.app.models.task import Task
        from backend.app.models.action import Action
        from backend.app.models.profile_update import ProfileUpdate
        from backend.app.models.search import TrendingTopic, TopicTweet, SearchedUser

        # Drop all tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            logger.info("Dropped all tables")

        # Create all tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Created all tables")

        # Create default settings
        async with async_session() as session:
            async with session.begin():
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

        logger.info("Database setup completed successfully!")

    except Exception as e:
        logger.error(f"Error setting up database: {str(e)}")
        raise

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(setup_database())
    except KeyboardInterrupt:
        logger.info("Setup interrupted by user")
    except Exception as e:
        logger.error(f"Setup failed: {str(e)}")
        exit(1)
    finally:
        loop.close()
