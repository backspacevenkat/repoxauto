import asyncio
import logging
from sqlalchemy import select
from backend.app.database import init_db, get_session
from backend.app.models.task import Task
from backend.app.services.task_queue import TaskQueue

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def debug_task(task_id: int):
    await init_db()
    async with get_session() as session:
        # Get the task
        result = await session.execute(
            select(Task).where(Task.id == task_id)
        )
        task = result.scalar_one_or_none()
        
        if not task:
            print(f"Task {task_id} not found")
            return
            
        print(f"\nFound task {task_id}:")
        print(f"Type: {task.type}")
        print(f"Status: {task.status}")
        print(f"Input params: {task.input_params}")
        
        # Try to process the task
        print("\nAttempting to process task...")
        task_queue = TaskQueue(get_session)
        await task_queue.start()
        
        # Wait for a bit to see if task gets processed
        print("Waiting for task processing...")
        for _ in range(30):  # Wait up to 30 seconds
            await asyncio.sleep(1)
            await session.refresh(task)
            print(f"Task status: {task.status}")
            if task.status in ['completed', 'failed']:
                break
                
        if task.status == 'completed':
            print("\nTask completed successfully!")
            print(f"Result: {task.result}")
        elif task.status == 'failed':
            print("\nTask failed!")
            print(f"Error: {task.error}")
        else:
            print("\nTask did not complete in time")
            
        await task_queue.stop()

if __name__ == "__main__":
    task_id = 9  # The last task ID from your curl commands
    asyncio.run(debug_task(task_id))
