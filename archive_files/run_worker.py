#!/usr/bin/env python3
import os
import sys
import asyncio
import logging
from backend.app.database import init_db
from backend.app.services.task_queue import TaskQueue
from backend.app.database import get_session

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler('logs/worker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Global task reference
main_task = None

def handle_signal(signum, frame):
    """Handle termination signals"""
    global main_task
    logger.info(f"Received signal {signum}")
    if main_task and not main_task.done():
        main_task.cancel()

async def main():
    global main_task
    task_queue = None
    try:
        # Initialize database
        await init_db()
        logger.info("Database initialized")

        # Create and start task queue
        task_queue = TaskQueue(get_session)
        await task_queue.start()
        logger.info("Task queue worker started")

        # Keep the worker running
        try:
            stop_event = asyncio.Event()
            await asyncio.shield(stop_event.wait())
        except asyncio.CancelledError:
            # Let the cancellation propagate after cleanup
            raise

    except asyncio.CancelledError:
        logger.info("Worker received shutdown signal")
    except Exception as e:
        logger.error(f"Error in worker process: {e}")
    finally:
        if task_queue:
            try:
                async with asyncio.timeout(5):  # 5 second timeout
                    await task_queue.stop()
                    logger.info("Worker stopped")
            except asyncio.TimeoutError:
                logger.warning("Worker stop timed out")
            except Exception as e:
                logger.error(f"Error stopping worker: {e}")

if __name__ == "__main__":
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    # Set up signal handlers
    import signal
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    # Create and run the main task
    main_task = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        main_task = loop.create_task(main())
        loop.run_until_complete(main_task)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
        if main_task and not main_task.done():
            main_task.cancel()
            try:
                loop.run_until_complete(main_task)
            except asyncio.CancelledError:
                pass
    finally:
        loop.close()
