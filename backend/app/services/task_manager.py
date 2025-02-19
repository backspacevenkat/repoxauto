import asyncio
import logging
import time
from typing import List, Dict, Set, Optional, Literal
from enum import Enum
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, literal_column
from ..models.account import Account, OAuthSetupState
from ..models.task import Task
from ..models.settings import SystemSettings
from ..schemas.settings import WorkerStatus, WorkerUtilization
from .task_queue import TaskQueue

logger = logging.getLogger(__name__)

class QueueStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    PAUSED = "paused"

class TaskManager:
    _instance: Optional['TaskManager'] = None

    def __init__(self, db_factory):
        if TaskManager._instance is not None:
            raise Exception("TaskManager is a singleton. Use get_instance() instead.")
        self._db_factory = db_factory  # Store factory function
        self.settings = None
        self.active_workers: Set[Account] = set()
        self.available_workers: List[Account] = []
        self.worker_tasks: Dict[Account, List[Task]] = {}
        self.worker_status: Dict[Account, str] = {}
        self.worker_health: Dict[Account, str] = {}
        self.worker_completed: Dict[Account, float] = {}  # Changed to float for timestamp
        self.current_batch: int = 1  # Track current batch number
        self.task_batch: Dict[Task, int] = {}  # Map tasks to their batch numbers
        self.worker_queue: List[Account] = []  # Queue of workers for rotatio
        self._monitor_task = None
        self.queue_status = QueueStatus.STOPPED
        self.task_queue = TaskQueue(db_factory)  # Initialize TaskQueue with factory

    def set_db(self, db_factory):
        """Set or update the database factory"""
        self._db_factory = db_factory
        self.task_queue = TaskQueue(db_factory)  # Reinitialize TaskQueue with factory

    async def _get_session(self) -> AsyncSession:
        """Create a new database session"""
        if self._db_factory is None:
            raise ValueError("Database factory not initialized")
        return self._db_factory()

    async def initialize(self, session: Optional[AsyncSession] = None):
        """Initialize the task manager"""
        try:
            # Create new session if not provided
            if session is None:
                session = await self._get_session()
                session_owner = True
            else:
                session_owner = False

            try:
                # Initialize core components
                await self._initialize_internal(session)
                
                # Start worker monitor after initialization
                if self._monitor_task:
                    self._monitor_task.cancel()
                    try:
                        await self._monitor_task
                    except asyncio.CancelledError:
                        pass
                self._monitor_task = asyncio.create_task(self.monitor_workers())
                
                logger.info("Task manager initialized successfully")
            finally:
                # Only close session if we created it
                if session_owner:
                    await session.close()
            
        except Exception as e:
            logger.error(f"Failed to initialize task manager: {e}")
            await self.cleanup()
            raise

    async def _initialize_internal(self, session: AsyncSession):
        """Internal initialization with active session"""
        # Test database connection
        try:
            await session.execute(select(literal_column('1')))
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            raise ValueError(f"Invalid database session: {e}")
        
        # Initialize core components
        await self.refresh_settings(session)
        if not self.settings:
            raise ValueError("Failed to initialize system settings")
            
        await self.refresh_workers(session)
        if not self.available_workers:
            logger.warning("No available workers found during initialization")
        
        # Initialize TaskQueue if needed
        if not self.task_queue:
            self.task_queue = TaskQueue(self._db_factory)
        
        self.queue_status = QueueStatus.STOPPED

    async def refresh_settings(self, session: Optional[AsyncSession] = None):
        """Get latest settings from database"""
        if session is None:
            session = await self._get_session()
            try:
                async with session.begin():
                    return await self._refresh_settings_internal(session)
            finally:
                await session.close()
        else:
            return await self._refresh_settings_internal(session)

    async def _refresh_settings_internal(self, session: AsyncSession):
        """Internal method to refresh settings with a given session"""
        result = await session.execute(select(SystemSettings).limit(1))
        settings = result.scalar_one_or_none()
        
        if not settings:
            # Create default settings if none exist
            settings = SystemSettings()
            session.add(settings)
            await session.commit()
        
        self.settings = settings
        return settings

    async def refresh_workers(self, session: Optional[AsyncSession] = None):
        """Refresh the list of available workers"""
        try:
            if session is None:
                session = await self._get_session()
                try:
                    async with session.begin():
                        return await self._refresh_workers_internal(session)
                finally:
                    await session.close()
            else:
                return await self._refresh_workers_internal(session)

        except Exception as e:
            logger.error(f"Error refreshing workers: {e}")
            return []

    async def _refresh_workers_internal(self, session: AsyncSession):
        """Internal method to refresh workers with a given session"""
        try:
            # Test if session is valid
            await session.execute(select(literal_column('1')))
        except Exception as e:
            logger.error(f"Database session is invalid: {e}")
            # Reset instance to force new session on next use
            await TaskManager.reset_instance()
            return []

        # Get all worker accounts with proper options
        stmt = (
            select(Account)
            .where(
                Account.act_type == 'worker',
                Account.is_worker == True,
                Account.deleted_at.is_(None)
            )
            .execution_options(populate_existing=True)
        )
        result = await session.execute(stmt)
        all_workers = list(result.scalars().all())
        
        # Filter and handle oauth setup status
        self.available_workers = []
        for worker in all_workers:
            try:
                # Ensure worker data is fresh
                await session.refresh(worker)
                
                # Handle string status (legacy)
                if isinstance(worker.oauth_setup_status, str):
                    if worker.oauth_setup_status == 'NEEDS_SETUP':
                        worker.oauth_setup_status = OAuthSetupState.PENDING
                        session.add(worker)
                
                # Include worker if status is valid
                if worker.oauth_setup_status in [OAuthSetupState.COMPLETED, OAuthSetupState.PENDING]:
                    self.available_workers.append(worker)
                else:
                    logger.warning(f"Worker {worker.account_no} has invalid oauth setup status: {worker.oauth_setup_status}")
            except Exception as e:
                logger.error(f"Error processing worker {worker.account_no}: {e}")
                continue

        # Commit any status updates
        if session.in_transaction():
            await session.commit()
        
        return self.available_workers

    async def add_task(self, session: AsyncSession, task_type: str, input_params: dict, priority: int = 0) -> Task:
        """Create and assign a new task"""
        try:
            # Create task using TaskQueue
            task = await self.task_queue.add_task(
                session=session,
                task_type=task_type,
                input_params=input_params,
                priority=priority
            )
            
            if task:
                # Always assign task to a worker
                await self.assign_tasks([task], session)
            
            return task
            
        except Exception as e:
            logger.error(f"Error adding task: {e}")
            raise

    async def get_task(self, session: AsyncSession, task_id: int) -> Optional[Task]:
        """Get task by ID with relationships loaded"""
        try:
            # Use joinedload to load relationships
            stmt = (
                select(Task)
                .where(Task.id == task_id)
                .execution_options(populate_existing=True)
            )
            result = await session.execute(stmt)
            task = result.scalar_one_or_none()
            
            # Ensure worker_account is loaded if exists
            if task and task.worker_account_id:
                await session.refresh(task, ['worker_account'])
            
            return task
        except Exception as e:
            logger.error(f"Error getting task {task_id}: {e}")
            raise

    async def get_task_status(self, session: AsyncSession, task_id: int) -> Optional[Task]:
        """Get task status and details"""
        return await self.get_task(session, task_id)

    async def assign_tasks(self, tasks: List[Task], session: AsyncSession) -> Dict[Account, List[Task]]:
        """Distribute tasks evenly among all available workers using round-robin"""
        try:
            if not self.available_workers:
                await self.refresh_workers(session)
                
            if not self.available_workers:
                raise Exception("No workers available")
                
            # Get tasks that need assignment
            pending_tasks = [t for t in tasks if not t.worker_account_id]
            if not pending_tasks:
                return self.worker_tasks

            # Initialize worker queue if empty
            if not self.worker_queue:
                self.worker_queue = list(self.available_workers)
                
            # All new tasks start in batch 1
            if self.current_batch == 0:
                self.current_batch = 1
            
            # Distribute tasks in round-robin fashion
            for task in pending_tasks:
                # Get next worker from queue
                if not self.worker_queue:
                    self.worker_queue = list(self.available_workers)
                worker = self.worker_queue.pop(0)
                
                # Initialize worker's task list if needed
                if worker not in self.worker_tasks:
                    self.worker_tasks[worker] = []
                    if worker not in self.worker_completed:
                        self.worker_completed[worker] = time.time()
                
                # Assign task to worker
                self.worker_tasks[worker].append(task)
                self.task_batch[task] = self.current_batch
                
                # Update task in database
                task.worker_account_id = worker.id
                task.status = "pending"  # Start as pending, will be set to locked then running by task queue
                session.add(task)
                logger.info(f"Assigned task {task.id} to worker {worker.account_no} (batch {self.current_batch})")
            
            await session.commit()
            
            # Log assignments
            for worker, assigned_tasks in self.worker_tasks.items():
                logger.info(f"Worker {worker.account_no} assigned {len(assigned_tasks)} tasks")
                
            return self.worker_tasks
            
        except Exception as e:
            logger.error(f"Error assigning tasks: {e}")
            raise

    async def activate_initial_workers(self, session: Optional[AsyncSession] = None):
        """Activate initial set of workers based on settings"""
        if not self.settings:
            await self.refresh_settings(session)
            
        max_workers = self.settings.max_concurrent_workers
        
        # Sort workers by rate limits and last active time
        sorted_workers = sorted(
            self.available_workers,
            key=lambda w: (
                w.current_15min_requests,  # Rate limit usage
                self.worker_completed.get(w, 0)  # Last completion time
            )
        )
        
        # Activate workers with lowest rate limits
        available = [w for w in sorted_workers if w not in self.active_workers]
        for worker in available[:max_workers]:
            await self.activate_worker(worker, session)

    async def activate_worker(self, worker: Account, session: Optional[AsyncSession] = None) -> bool:
        """Activate a single worker"""
        if not self.settings:
            await self.refresh_settings(session)
            
        if len(self.active_workers) < self.settings.max_concurrent_workers:
            self.active_workers.add(worker)
            self.worker_status[worker] = "active"
            # Initialize completion time when activated
            if worker not in self.worker_completed:
                self.worker_completed[worker] = time.time()
            logger.info(f"Activated worker {worker.account_no}")
            return True
            
        logger.warning(f"Could not activate worker {worker.account_no}: Max concurrent workers reached")
        return False

    async def deactivate_worker(self, worker: Account):
        """Deactivate a worker"""
        if worker in self.active_workers:
            self.active_workers.remove(worker)
            self.worker_status[worker] = "inactive"
            logger.info(f"Deactivated worker {worker.account_no}")

    async def get_next_available_worker(self) -> Account:
        """Get next available worker that isn't active"""
        for worker in self.available_workers:
            if (worker not in self.active_workers and 
                worker.current_15min_requests < self.settings.max_requests_per_worker):
                return worker
        return None

    async def is_worker_healthy(self, worker: Account) -> bool:
        """Check if worker is healthy and not rate limited"""
        # Check rate limits
        if worker.current_15min_requests >= self.settings.max_requests_per_worker:
            logger.warning(f"Worker {worker.account_no} is rate limited")
            return False
            
        # Initialize worker completion time if not set
        if worker not in self.worker_completed:
            self.worker_completed[worker] = time.time()
            
        # Only check completion time if worker has assigned tasks
        if worker in self.worker_tasks and self.worker_tasks[worker]:
            last_success = self.worker_completed.get(worker, time.time())
            if time.time() - last_success > 600:  # Increased to 10 minutes
                logger.warning(f"Worker {worker.account_no} has not completed tasks in 10 minutes")
                return False
            
        return True

    async def handle_worker_failure(self, worker: Account, session: Optional[AsyncSession] = None):
        """Handle failed worker and reassign its tasks"""
        logger.info(f"Handling failure for worker {worker.account_no}")
        
        # Get pending tasks
        pending_tasks = self.worker_tasks.get(worker, [])
        if not pending_tasks:
            return
            
        # Remove from active workers
        await self.deactivate_worker(worker)
        self.worker_health[worker] = "failed"
        
        # Find new worker
        new_worker = await self.get_next_available_worker()
        if new_worker:
            await self.activate_worker(new_worker, session)
            if new_worker in self.worker_tasks:
                self.worker_tasks[new_worker].extend(pending_tasks)
            else:
                self.worker_tasks[new_worker] = pending_tasks
                
            # Update tasks in database
            if session is None:
                session = await self._get_session()
                try:
                    async with session.begin():
                        await self._update_tasks_worker(pending_tasks, new_worker, session)
                finally:
                    await session.close()
            else:
                await self._update_tasks_worker(pending_tasks, new_worker, session)
                
            logger.info(f"Reassigned {len(pending_tasks)} tasks from {worker.account_no} to {new_worker.account_no}")
        else:
            logger.error(f"No available workers to handle tasks from failed worker {worker.account_no}")

    async def _update_tasks_worker(self, tasks: List[Task], new_worker: Account, session: AsyncSession):
        """Internal method to update tasks with new worker"""
        for task in tasks:
            task.worker_account_id = new_worker.id
            session.add(task)

    async def process_tasks(self, session: Optional[AsyncSession] = None):
        """Process tasks assigned to workers and handle worker rotation"""
        try:
            # Only process if queue is running
            if self.queue_status != QueueStatus.RUNNING:
                return

            if session is None:
                session = await self._get_session()
                try:
                    async with session.begin():
                        await self._process_tasks_internal(session)
                finally:
                    await session.close()
            else:
                await self._process_tasks_internal(session)

        except Exception as e:
            logger.error(f"Error processing tasks: {e}")
            raise

    async def _process_tasks_internal(self, session: AsyncSession):
        """Internal method to process tasks with a given session"""
        # Get all assigned pending tasks
        stmt = (
            select(Task)
            .where(
                Task.status == "pending",
                Task.worker_account_id != None
            )
            .order_by(Task.priority.desc(), Task.created_at.asc())
        )
        result = await session.execute(stmt)
        pending_task_ids = [task.id for task in result.scalars().all()]
        
        # Load fresh task instances
        pending_tasks = await self._load_tasks_by_ids(session, pending_task_ids)
        if not pending_tasks:
            return

        # Handle worker rotation with fresh instances
        await self.rotate_workers(session)

        # Group tasks by batch
        tasks_by_batch = {}
        for task in pending_tasks:
            batch = self.task_batch.get(task, 1)  # Default to batch 1 if not set
            if batch not in tasks_by_batch:
                tasks_by_batch[batch] = []
            tasks_by_batch[batch].append(task)

        # Process tasks batch by batch
        for batch in sorted(tasks_by_batch.keys()):
            batch_tasks = tasks_by_batch[batch]
            logger.info(f"Processing batch {batch} with {len(batch_tasks)} tasks")

            # Get fresh worker instances for this batch
            worker_ids = list(set(task.worker_account_id for task in batch_tasks))
            batch_workers = await self._load_workers_by_ids(session, worker_ids)
            
            # Create worker ID lookup for efficiency
            worker_lookup = {w.id: w for w in batch_workers}

            # Group tasks by worker within batch
            worker_batch_tasks = {}
            for task in batch_tasks:
                worker = worker_lookup.get(task.worker_account_id)
                if worker:
                    if worker not in worker_batch_tasks:
                        worker_batch_tasks[worker] = []
                    worker_batch_tasks[worker].append(task)

            # Update task statuses for active workers
            for worker, tasks in worker_batch_tasks.items():
                if worker in self.active_workers and await self.is_worker_healthy(worker):
                    for task in tasks:
                        if task.status in ["pending", "locked"]:
                            task.update_status("running")
                            session.add(task)
                            logger.info(f"Started task {task.id} with worker {worker.account_no} (batch {batch})")

            # Update worker task assignments with fresh instances
            for worker, tasks in worker_batch_tasks.items():
                if worker not in self.worker_tasks:
                    self.worker_tasks[worker] = []
                self.worker_tasks[worker].extend(tasks)

    async def rotate_workers(self, session: Optional[AsyncSession] = None):
        """Rotate workers based on task batches and rate limits"""
        try:
            if not self.settings:
                await self.refresh_settings(session)

            max_workers = self.settings.max_concurrent_workers

            # Get fresh instances of active workers
            active_worker_ids = [w.id for w in self.active_workers]
            active_workers = await self._load_workers_by_ids(session, active_worker_ids)

            # Deactivate rate-limited or unhealthy workers
            for worker in active_workers:
                if not await self.is_worker_healthy(worker):
                    await self.deactivate_worker(worker)

            # Get fresh instances of available workers
            available_worker_ids = [w.id for w in self.available_workers]
            available_workers = await self._load_workers_by_ids(session, available_worker_ids)

            # Get workers with pending tasks in current batch
            current_batch_workers = []
            for worker in available_workers:
                # Get fresh task instances for this worker
                current_batch_tasks = await self._get_current_batch_tasks(session, worker)
                if current_batch_tasks:
                    current_batch_workers.append((worker, len(current_batch_tasks)))

            # Sort workers by number of pending tasks in current batch
            current_batch_workers.sort(key=lambda x: x[1], reverse=True)
            
            # Get fresh instances of active workers again after potential changes
            active_worker_ids = [w.id for w in self.active_workers]
            active_workers = await self._load_workers_by_ids(session, active_worker_ids)
            
            # Deactivate workers not in current batch
            for worker in active_workers:
                if not any(w[0].id == worker.id for w in current_batch_workers):
                    await self.deactivate_worker(worker)

            # Activate workers with tasks in current batch
            current_active = len(self.active_workers)
            for worker, _ in current_batch_workers:
                if current_active >= max_workers:
                    break
                if worker not in self.active_workers:
                    if worker.current_15min_requests < self.settings.max_requests_per_worker:
                        if await self.activate_worker(worker, session):
                            current_active += 1

            logger.info(f"Active workers after rotation: {len(self.active_workers)}/{max_workers}")

        except Exception as e:
            logger.error(f"Error rotating workers: {e}")
            raise

    async def _load_tasks_by_ids(self, session: AsyncSession, task_ids: List[int]) -> List[Task]:
        """Load fresh task instances bound to current session"""
        if not task_ids:
            return []
            
        stmt = (
            select(Task)
            .where(Task.id.in_(task_ids))
            .execution_options(populate_existing=True)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def _load_workers_by_ids(self, session: AsyncSession, worker_ids: List[int]) -> List[Account]:
        """Load fresh worker instances bound to current session"""
        if not worker_ids:
            return []
            
        stmt = (
            select(Account)
            .where(Account.id.in_(worker_ids))
            .execution_options(populate_existing=True)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def _get_current_batch_tasks(self, session: AsyncSession, worker: Account) -> List[Task]:
        """Get fresh task instances for current batch"""
        worker_tasks = self.worker_tasks.get(worker, [])
        task_ids = [
            t.id for t in worker_tasks 
            if t.status == "pending" and self.task_batch.get(t, 1) == self.current_batch
        ]
        return await self._load_tasks_by_ids(session, task_ids)

    async def _get_next_batch_tasks(self, session: AsyncSession, worker: Account) -> List[Task]:
        """Get fresh task instances for next batch"""
        worker_tasks = self.worker_tasks.get(worker, [])
        task_ids = [
            t.id for t in worker_tasks 
            if t.status == "pending" and self.task_batch.get(t, 1) > self.current_batch
        ]
        return await self._load_tasks_by_ids(session, task_ids)

    async def monitor_workers(self):
        """Monitor worker health and handle failures"""
        while True:
            try:
                # Only monitor if queue is running
                if self.queue_status == QueueStatus.RUNNING:
                    session = await self._get_session()
                    try:
                        async with session.begin():
                            # Get fresh worker instances
                            active_worker_ids = [w.id for w in self.active_workers]
                            active_workers = await self._load_workers_by_ids(session, active_worker_ids)
                            
                            # Process pending tasks with fresh instances
                            await self.process_tasks(session)
                            
                            # Check worker health and update batch status
                            completed_current_batch = True
                            for worker in active_workers:
                                if not await self.is_worker_healthy(worker):
                                    await self.handle_worker_failure(worker, session)
                                else:
                                    # Check current batch tasks with fresh instances
                                    current_batch_tasks = await self._get_current_batch_tasks(session, worker)
                                    if current_batch_tasks:
                                        completed_current_batch = False
                            
                            # Move to next batch if current batch is complete
                            if completed_current_batch:
                                has_next_batch = False
                                available_worker_ids = [w.id for w in self.available_workers]
                                available_workers = await self._load_workers_by_ids(session, available_worker_ids)
                                
                                for worker in available_workers:
                                    next_batch_tasks = await self._get_next_batch_tasks(session, worker)
                                    if next_batch_tasks:
                                        has_next_batch = True
                                        self.current_batch += 1
                                        logger.info(f"Moving to batch {self.current_batch}")
                                        break
                                
                                if not has_next_batch:
                                    logger.info("All batches completed")
                            
                            # Rotate workers based on current batch
                            await self.rotate_workers(session)
                    finally:
                        await session.close()
                
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.error(f"Error in worker monitor: {str(e)}")
                await asyncio.sleep(30)  # Wait before retrying

    def get_status(self) -> Dict[str, any]:
        """Get comprehensive status report"""
        total_completed = sum(1 for v in self.worker_completed.values() if v > 0)
        total_pending = sum(len(tasks) for tasks in self.worker_tasks.values())

        worker_utilization = {
            worker.account_no: {
                "assigned_tasks": len(self.worker_tasks.get(worker, [])),
                "completed_tasks": 1 if self.worker_completed.get(worker, 0) > 0 else 0,
                "is_active": worker in self.active_workers,
                "health_status": self.worker_health.get(worker, "unknown"),
                "rate_limit_status": {
                    "requests_15min": worker.current_15min_requests,
                    "requests_24h": worker.current_24h_requests,
                    "last_rate_limit_reset": worker.last_rate_limit_reset.isoformat() if worker.last_rate_limit_reset else None
                }
            }
            for worker in self.available_workers
        }

        return {
            "total_workers": len(self.available_workers),
            "active_workers": len(self.active_workers),
            "tasks_completed": total_completed,
            "tasks_pending": total_pending,
            "worker_utilization": worker_utilization,
            "queue_status": self.queue_status.value
        }

    async def start(self, session: Optional[AsyncSession] = None):
        """Start processing tasks"""
        try:
            # Create new session if not provided
            if session is None:
                async with self._db_factory() as session:
                    async with session.begin():
                        return await self._start_internal(session)
            else:
                # Use provided session
                async with session.begin():
                    return await self._start_internal(session)
            
        except Exception as e:
            logger.error(f"Failed to start task queue: {e}")
            self.queue_status = QueueStatus.STOPPED
            raise

    async def _start_internal(self, session: AsyncSession) -> bool:
        """Internal start method with active session"""
        # Verify workers
        if not self.available_workers:
            await self.refresh_workers(session)
            if not self.available_workers:
                raise ValueError("No available workers found")
        
        # Verify active workers
        if not self.active_workers:
            await self.activate_initial_workers(session)
            if not self.active_workers:
                raise ValueError("Failed to activate any workers")
        
        # Start queue if stopped
        if self.queue_status == QueueStatus.STOPPED:
            self.queue_status = QueueStatus.RUNNING
            
            # Start TaskQueue with settings
            if self.settings:
                await self.task_queue.start(
                    max_workers=self.settings.max_concurrent_workers,
                    requests_per_worker=self.settings.max_requests_per_worker,
                    request_interval=15  # Default interval
                )
            
            # Process any pending tasks
            await self.process_tasks(session)
            
            logger.info(f"Task queue started with {len(self.active_workers)} active workers")
            return True
            
        logger.info(f"Task queue already running with {len(self.active_workers)} active workers")
        return False

    async def stop(self):
        """Stop the task manager and cleanup resources"""
        logger.info("Stopping task manager...")
        self.queue_status = QueueStatus.STOPPED
        if self.task_queue:
            await self.task_queue.stop()
        await self.cleanup()
        logger.info("Task manager stopped")

    async def pause(self):
        """Pause task processing"""
        if self.queue_status == QueueStatus.RUNNING:
            self.queue_status = QueueStatus.PAUSED
            logger.info("Task queue paused")
            return True
        return False

    async def resume(self):
        """Resume task processing"""
        if self.queue_status == QueueStatus.PAUSED:
            self.queue_status = QueueStatus.RUNNING
            logger.info("Task queue resumed")
            return True
        return False

    async def cleanup(self):
        """Cleanup resources"""
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    @classmethod
    async def get_instance(cls, db_factory = None) -> 'TaskManager':
        """Get or create the TaskManager instance"""
        if cls._instance is None:
            if db_factory is None:
                raise ValueError("Database factory required for initialization")
            cls._instance = cls(db_factory)
            async with db_factory() as session:
                await cls._instance.initialize(session=session)
        else:
            # Update database factory if provided
            if db_factory is not None:
                cls._instance.set_db(db_factory)
            
        return cls._instance

    @classmethod
    async def reset_instance(cls):
        """Reset the singleton instance and cleanup resources"""
        if cls._instance:
            try:
                # Stop task queue and cleanup
                await cls._instance.stop()
                # Clear instance
                cls._instance = None
            except Exception as e:
                logger.error(f"Error during instance reset: {e}")
                # Ensure instance is cleared even on error
                cls._instance = None
