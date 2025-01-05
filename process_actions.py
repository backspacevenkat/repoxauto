#!/usr/bin/env python3
import asyncio
import logging
import sys
import argparse
from pathlib import Path
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f'logs/process_actions_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)

logger = logging.getLogger(__name__)

async def main():
    parser = argparse.ArgumentParser(description='Process Twitter actions from CSV file')
    parser.add_argument('csv_file', help='Path to CSV file containing actions')
    parser.add_argument('--workers', type=int, default=1, help='Number of worker processes (default: 1)')
    parser.add_argument('--monitor', action='store_true', help='Monitor mode - show real-time status')
    args = parser.parse_args()

    # Validate CSV file
    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        logger.error(f"CSV file not found: {csv_path}")
        sys.exit(1)

    try:
        # Import here to avoid circular imports
        from backend.app.scripts.process_actions_csv import process_actions_file
        from backend.app.workers.action_worker import ActionWorker
        
        # Start worker processes
        workers = []
        for i in range(args.workers):
            worker = ActionWorker()
            worker_task = asyncio.create_task(worker.start())
            workers.append((worker, worker_task))
            logger.info(f"Started worker {i+1}")

        # Process CSV file
        logger.info(f"Processing actions from {csv_path}")
        results = await process_actions_file(str(csv_path))
        
        if results["errors"]:
            logger.error("\nErrors encountered:")
            for error in results["errors"]:
                logger.error(f"- {error}")

        # Summary
        logger.info(f"""
        Processing Summary:
        - Total actions: {results["total"]}
        - Successfully queued: {results["queued"]}
        - Failed: {results["failed"]}
        - Success rate: {(results["queued"] / results["total"] * 100 if results["total"] > 0 else 0):.1f}%
        """)

        if args.monitor:
            try:
                while True:
                    # TODO: Add real-time status monitoring
                    # This could show:
                    # - Actions completed/pending/failed
                    # - Current rate limits
                    # - Worker status
                    await asyncio.sleep(5)
            except KeyboardInterrupt:
                logger.info("\nMonitoring stopped by user")

        # Wait for all actions to complete
        logger.info("Waiting for queued actions to complete...")
        await asyncio.sleep(5)  # Give time for actions to start processing

        # Stop workers
        for worker, task in workers:
            await worker.stop()
            try:
                await task
            except asyncio.CancelledError:
                pass

        logger.info("All workers stopped")
        
        # Exit with error if any actions failed
        sys.exit(0 if results["failed"] == 0 else 1)

    except KeyboardInterrupt:
        logger.info("\nProcess interrupted by user")
        # Stop workers
        for worker, task in workers:
            await worker.stop()
            try:
                await task
            except asyncio.CancelledError:
                pass
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    # Create logs directory if it doesn't exist
    Path('logs').mkdir(exist_ok=True)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProcess interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nFatal error: {str(e)}")
        sys.exit(1)
