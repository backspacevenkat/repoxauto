import csv
import io
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Path, status, Request
from sqlalchemy import func, select, and_, case
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db, async_session
from ..models.task import Task
from ..models.account import Account, ValidationState
from ..services.task_queue import TaskQueue
from ..schemas.task import (
    TaskCreate, TaskRead, TaskBulkCreate, TaskBulkResponse,
    TaskList, TaskStats, TaskType, TaskStatus, TaskUpdate
)
import logging

logger = logging.getLogger(__name__)
router = APIRouter()
task_queue = TaskQueue(get_db)

async def verify_worker_accounts() -> List[Account]:
    """Verify that there are available worker accounts"""
    try:
        async with async_session() as session:
            # Get all worker accounts
            logger.info("Querying worker accounts...")
            stmt = select(Account).where(Account.act_type == 'worker')
            result = await session.execute(stmt)
            workers = list(result.scalars().all())  # Convert to list to avoid session issues
            logger.info(f"Found {len(workers)} total worker accounts")
            
            if not workers:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No worker accounts available. Please add worker accounts before creating tasks."
                )
                
            # Log worker account states
            for worker in workers:
                logger.info(f"Found worker {worker.account_no}: active={worker.is_active}, validation={worker.validation_in_progress}")
            
            # Check for active workers
            logger.info("Checking for active workers...")
            active_workers = []
            for w in workers:
                logger.info(f"Worker {w.account_no}: active={w.is_active}, validation={w.validation_in_progress}, type={type(w.validation_in_progress)}")
                if w.is_active and w.validation_in_progress == ValidationState.COMPLETED:
                    active_workers.append(w)
            if not active_workers:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"No active worker accounts available. Found {len(workers)} workers but none are active and completed validation."
                )
                
            logger.info(f"Found {len(active_workers)} active workers ready for tasks")
            return active_workers
    except Exception as e:
        logger.error(f"Error verifying worker accounts: {str(e)}")
        raise

@router.post("/create", response_model=TaskRead)
async def create_task(
    task_data: TaskCreate,
    session: AsyncSession = Depends(get_db)
):
    """Create a single task"""
    try:
        # Verify worker accounts
        active_workers = await verify_worker_accounts()
        if not active_workers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active worker accounts available"
            )

        # Validate input parameters based on task type
        if task_data.type in [TaskType.SCRAPE_PROFILE, TaskType.SCRAPE_TWEETS]:
            if not task_data.input_params.get("username"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username is required for scraping tasks"
                )
        elif task_data.type in [TaskType.LIKE_TWEET, TaskType.RETWEET, TaskType.REPLY, TaskType.QUOTE]:
            if not task_data.input_params.get("tweet_id"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Tweet ID is required for tweet interaction tasks"
                )
            if task_data.type in [TaskType.REPLY, TaskType.QUOTE]:
                meta_data = task_data.input_params.get("meta_data", {})
                if not meta_data or not meta_data.get("text_content"):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"{task_data.type} requires text content in meta_data"
                    )
        elif task_data.type == TaskType.CREATE:
            meta_data = task_data.input_params.get("meta_data", {})
            if not meta_data or not meta_data.get("text_content"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Create tweet requires text content in meta_data"
                )

        task = await task_queue.add_task(
            session,
            task_data.type,
            task_data.input_params,
            task_data.priority
        )
        await session.commit()
        return task
    except Exception as e:
        logger.error(f"Error creating task: {str(e)}")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create task: {str(e)}"
        )

@router.post("/bulk", response_model=TaskBulkResponse)
async def create_bulk_tasks(
    bulk_data: TaskBulkCreate,
    session: AsyncSession = Depends(get_db)
):
    """Create multiple tasks from a list of usernames"""
    try:
        # Verify worker accounts
        active_workers = await verify_worker_accounts()
        
        # Calculate max concurrent tasks based on rate limits
        max_tasks = len(active_workers) * 900  # 900 requests per 15min per account
        if len(bulk_data.usernames) > max_tasks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Too many tasks. Maximum {max_tasks} tasks allowed with current worker accounts."
            )

        tasks = []
        async with async_session() as session:
            for username in bulk_data.usernames:
                if not username:
                    continue

                input_params = {
                    "username": username
                }
                if bulk_data.task_type == TaskType.SCRAPE_TWEETS:
                    input_params.update({
                        "count": bulk_data.count,
                        "hours": bulk_data.hours,
                        "max_replies": bulk_data.max_replies
                    })

                task = await task_queue.add_task(
                    session,
                    bulk_data.task_type,
                    input_params,
                    bulk_data.priority
                )
                tasks.append(task)
            await session.commit()

        return TaskBulkResponse(
            message=f"Created {len(tasks)} tasks",
            task_ids=[t.id for t in tasks]
        )
    except Exception as e:
        logger.error(f"Error creating bulk tasks: {str(e)}")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create bulk tasks: {str(e)}"
        )

@router.post("/upload", response_model=TaskBulkResponse)
async def create_tasks_from_csv(
    file: UploadFile = File(...),
    task_type: TaskType = Query(..., description="Type of task to create"),
    count: Optional[int] = Query(15, ge=1, le=100, description="Number of tweets to fetch (for tweet tasks)"),
    hours: Optional[int] = Query(24, ge=1, le=168, description="Hours to look back for tweets"),
    max_replies: Optional[int] = Query(7, ge=0, le=20, description="Maximum number of replies to fetch per tweet"),
    priority: Optional[int] = Query(0, ge=0, le=10, description="Task priority")
):
    """Create tasks from CSV file of usernames"""
    try:
        # Get active worker accounts
        active_workers = await verify_worker_accounts()
        if not active_workers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active worker accounts available"
            )

        if not file.filename.endswith('.csv'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must be a CSV"
            )

        content = await file.read()
        csv_file = io.StringIO(content.decode())
        csv_reader = csv.DictReader(csv_file)

        if 'Username' not in csv_reader.fieldnames:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CSV must have 'Username' column"
            )

        usernames = []
        for row in csv_reader:
            username = row['Username'].strip()
            if username:
                usernames.append(username)

        # Check rate limit capacity
        max_tasks = len(active_workers) * 900
        if len(usernames) > max_tasks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Too many usernames in CSV. Maximum {max_tasks} tasks allowed with current worker accounts."
            )

        tasks = []
        async with async_session() as session:
            for username in usernames:
                input_params = {
                    "username": username
                }
                if task_type == TaskType.SCRAPE_TWEETS:
                    input_params.update({
                        "count": count,
                        "hours": hours,
                        "max_replies": max_replies
                    })

                task = await task_queue.add_task(
                    session,
                    task_type,
                    input_params,
                    priority
                )
                tasks.append(task)
            await session.commit()

        return TaskBulkResponse(
            message=f"Created {len(tasks)} tasks from CSV",
            task_ids=[t.id for t in tasks]
        )
    except Exception as e:
        logger.error(f"Error creating tasks from CSV: {str(e)}")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create tasks from CSV: {str(e)}"
        )

@router.get("/list", response_model=TaskList)
async def list_tasks(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by task status"),
    type: Optional[str] = Query(None, description="Filter by task type"),
    session: AsyncSession = Depends(get_db)
):
    """Get paginated list of tasks with optional filters"""
    try:
        # Build query
        query = select(Task)
        if status:
            query = query.where(Task.status == status)
        if type:
            query = query.where(Task.type == type)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = await session.scalar(count_query)

        # Get paginated results
        query = query.order_by(Task.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(query)
        tasks = result.scalars().all()

        # Convert SQLAlchemy objects to dictionaries
        task_dicts = []
        for task in tasks:
            task_dict = {
                "id": task.id,
                "type": task.type,
                "status": task.status,
                "created_at": task.created_at,
                "started_at": task.started_at,
                "completed_at": task.completed_at,
                "input_params": task.input_params,
                "result": task.result,
                "error": task.error,
                "retry_count": task.retry_count,
                "execution_time": task.execution_time
            }
            task_dicts.append(task_dict)

        return TaskList(
            tasks=task_dicts,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size
        )
    except Exception as e:
        logger.error(f"Error listing tasks: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list tasks: {str(e)}"
        )

@router.get("/stats", response_model=TaskStats)
async def get_task_stats(
    session: AsyncSession = Depends(get_db)
):
    """Get task statistics"""
    try:
        # Get counts by status
        status_counts = await session.execute(
            select(Task.status, func.count())
            .group_by(Task.status)
        )
        counts = dict(status_counts.all())

        # Calculate average completion time for completed tasks
        avg_time = await session.scalar(
            select(func.avg(Task.completed_at - Task.started_at))
            .where(Task.status == TaskStatus.COMPLETED)
        )

        total = sum(counts.values())
        completed = counts.get(TaskStatus.COMPLETED, 0)

        # Get worker account stats
        # Get worker stats
        worker_stats = await session.execute(
            select(
                func.count().label('total_workers'),
                func.sum(
                    case(
                        (Account.last_validation_time > func.datetime('now', '-1 day'), 1),
                        else_=0
                    )
                ).label('active_workers'),
                func.sum(
                    case(
                        (Account.current_15min_requests >= 900, 1),
                        else_=0
                    )
                ).label('rate_limited_workers')
            )
            .where(Account.act_type == 'worker')
        )
        worker_counts = worker_stats.first()

        # Calculate tasks per minute
        if completed > 0 and avg_time:
            tasks_per_minute = 60 / avg_time.total_seconds()
        else:
            tasks_per_minute = 0

        return TaskStats(
            total_tasks=total,
            pending_tasks=counts.get(TaskStatus.PENDING, 0),
            running_tasks=counts.get(TaskStatus.RUNNING, 0),
            completed_tasks=completed,
            failed_tasks=counts.get(TaskStatus.FAILED, 0),
            average_completion_time=avg_time.total_seconds() if avg_time else None,
            success_rate=completed / total * 100 if total > 0 else 0,
            total_workers=worker_counts.total_workers or 0,
            active_workers=worker_counts.active_workers or 0,
            rate_limited_workers=worker_counts.rate_limited_workers or 0,
            tasks_per_minute=tasks_per_minute,
            estimated_completion_time=None  # Will be calculated by validator
        )
    except Exception as e:
        logger.error(f"Error getting task stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get task stats: {str(e)}"
        )

@router.get("/{task_id}", response_model=TaskRead)
async def get_task(
    task_id: int = Path(..., description="Task ID"),
    session: AsyncSession = Depends(get_db)
):
    """Get status and details of a specific task"""
    task = await task_queue.get_task_status(session, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    return task

@router.post("/{task_id}/update", response_model=TaskRead)
async def update_task_status(
    task_id: int,
    task_update: TaskUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db)
):
    """Update a task's status and broadcast the update via WebSocket."""
    try:
        task = await task_queue.get_task_status(session, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
            
        # Update task fields
        for field, value in task_update.dict(exclude_unset=True).items():
            setattr(task, field, value)
            
        await session.commit()

        # Broadcast update via WebSocket
        await request.app.state.connection_manager.broadcast({
            "type": "task_update",
            "task_id": task_id,
            "status": task.status,
            "result": task.result
        })

        return TaskRead.from_orm(task)
        
    except Exception as e:
        logger.error(f"Error updating task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/start")
async def start_task_queue():
    """Start the task queue processor"""
    try:
        await task_queue.start()
        return {"message": "Task queue started"}
    except Exception as e:
        logger.error(f"Error starting task queue: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start task queue: {str(e)}"
        )

@router.post("/stop")
async def stop_task_queue():
    """Stop the task queue processor"""
    try:
        await task_queue.stop()
        return {"message": "Task queue stopped"}
    except Exception as e:
        logger.error(f"Error stopping task queue: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop task queue: {str(e)}"
        )
