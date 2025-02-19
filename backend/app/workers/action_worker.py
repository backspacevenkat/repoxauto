import asyncio
import logging
import signal
import sys
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import db_manager
from ..services.action_processor import ActionProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/action_worker.log')
    ]
)

logger = logging.getLogger(__name__)

class ActionWorker:
    def __init__(self):
        self.running = False
        self.processor = None
        self.cleanup_task = None

    async def start(self):
        """Start the action worker"""
        logger.info("Starting action worker...")
        self.running = True

        # Set up signal handlers
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._signal_handler)

        try:
            # Start periodic cleanup task
            self.cleanup_task = asyncio.create_task(self._periodic_cleanup())
            
            # Main processing loop
            while self.running:
                try:
                    # Create new session for each iteration
                    session = db_manager.async_session()
                    async with session as session:
                        self.processor = ActionProcessor(session)
                        # Process queue
                        await self.processor._process_queue()
                    
                    # Wait before checking for new actions
                    await asyncio.sleep(5)
                    
                except Exception as e:
                    logger.error(f"Error in main processing loop: {str(e)}")
                    await asyncio.sleep(10)  # Wait longer on error

        except Exception as e:
            logger.error(f"Fatal error in action worker: {str(e)}")
        finally:
            await self.stop()

    async def stop(self):
        """Stop the action worker"""
        logger.info("Stopping action worker...")
        self.running = False
        
        # Cancel cleanup task
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Action worker stopped")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}")
        self.running = False

    async def _periodic_cleanup(self):
        """Run periodic cleanup tasks"""
        while self.running:
            try:
                # Create new session for cleanup
                session = db_manager.async_session()
                async with session as session:
                    processor = ActionProcessor(session)
                    await processor.cleanup()
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {str(e)}")
            
            # Run cleanup every 5 minutes
            await asyncio.sleep(300)

async def main():
    """Main entry point for the action worker"""
    worker = ActionWorker()
    
    try:
        await worker.start()
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
    finally:
        await worker.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Action worker terminated by user")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        sys.exit(1)
