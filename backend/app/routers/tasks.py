import csv
import io
import json
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Path, status, Request, Response
from sqlalchemy import func, select, and_, case, text, DateTime, Integer, literal_column
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db, db_manager
from ..models.task import Task
from ..models.account import Account, ValidationState, OAuthSetupState
from ..services.task_manager import TaskManager
from ..schemas.task import (
    TaskCreate, TaskRead, TaskBulkCreate, TaskBulkResponse,
    TaskList, TaskStats, TaskType, TaskStatus, TaskUpdate
)
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

def get_task_manager(request: Request):
    """Get the task manager instance from app state"""
    if not hasattr(request.app.state, 'task_manager'):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task manager not initialized"
        )
    return request.app.state.task_manager

async def verify_worker_accounts(request: Request, session: AsyncSession) -> List[Account]:
    """Verify that there are available worker accounts"""
    try:
        # Get task manager from app state
        task_manager = get_task_manager(request)
        
        # Refresh worker list
        await task_manager.refresh_workers()
        
        if not task_manager.available_workers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No worker accounts available. Please add worker accounts before creating tasks."
            )
        
        # Log worker states
        for worker in task_manager.available_workers:
            logger.info(f"Found worker {worker.account_no}: active={worker in task_manager.active_workers}, health={task_manager.worker_health.get(worker, 'unknown')}")
            
            # Skip workers with invalid oauth setup
            if worker.oauth_setup_status not in [OAuthSetupState.COMPLETED, OAuthSetupState.PENDING]:
                logger.warning(f"Worker {worker.account_no} has invalid oauth setup status: {worker.oauth_setup_status}")
                continue
        
        # Log available workers
        logger.info(f"Found {len(task_manager.available_workers)} total workers")
        
        return task_manager.available_workers
    except Exception as e:
        logger.error(f"Error verifying worker accounts: {str(e)}")
        raise

@router.post("/create", response_model=TaskRead)
async def create_task(
    task_data: TaskCreate,
    request: Request,
    session: AsyncSession = Depends(get_db)
):
    """Create a single task"""
    try:
        # Verify worker accounts
        active_workers = await verify_worker_accounts(request, session)
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

        task_manager = get_task_manager(request)
        task = await task_manager.add_task(
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
    request: Request,
    session: AsyncSession = Depends(get_db)
):
    """Create multiple tasks from a list of usernames"""
    try:
        # Verify worker accounts
        active_workers = await verify_worker_accounts(request, session)
        
        # Calculate max concurrent tasks based on rate limits
        max_tasks = len(active_workers) * 900  # 900 requests per 15min per account
        if len(bulk_data.usernames) > max_tasks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Too many tasks. Maximum {max_tasks} tasks allowed with current worker accounts."
            )

        tasks = []
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

            task_manager = get_task_manager(request)
            task = await task_manager.add_task(
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
    request: Request,
    file: UploadFile = File(...),
    task_type: TaskType = Query(..., description="Type of task to create"),
    count: Optional[int] = Query(15, ge=1, le=100, description="Number of tweets to fetch (for tweet tasks)"),
    hours: Optional[int] = Query(24, ge=1, le=168, description="Hours to look back for tweets"),
    max_replies: Optional[int] = Query(7, ge=0, le=20, description="Maximum number of replies to fetch per tweet"),
    priority: Optional[int] = Query(0, ge=0, le=10, description="Task priority"),
    session: AsyncSession = Depends(get_db)
):
    """Create tasks from CSV file of usernames"""
    try:
        # Get active worker accounts
        active_workers = await verify_worker_accounts(request, session)
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

            task_manager = get_task_manager(request)
            task = await task_manager.add_task(
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

@router.get("/stats")
async def get_task_stats(
    request: Request,
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

        # Get worker stats from task manager
        task_manager = get_task_manager(request)
        worker_status = task_manager.get_status()
        
        # Get rate limited workers count
        rate_limited_workers = sum(
            1 for worker_data in worker_status["worker_utilization"].values()
            if worker_data["rate_limit_status"]["requests_15min"] >= task_manager.settings.max_requests_per_worker
        )

        # Calculate tasks per minute
        if completed > 0 and avg_time:
            tasks_per_minute = 60 / avg_time.total_seconds()
        else:
            tasks_per_minute = 0

        data = {
            "total_tasks": total,
            "pending_tasks": counts.get(TaskStatus.PENDING, 0),
            "running_tasks": counts.get(TaskStatus.RUNNING, 0),
            "completed_tasks": completed,
            "failed_tasks": counts.get(TaskStatus.FAILED, 0),
            "average_completion_time": avg_time.total_seconds() if avg_time else None,
            "success_rate": completed / total * 100 if total > 0 else 0,
            "total_workers": worker_status["total_workers"],
            "active_workers": worker_status["active_workers"],
            "rate_limited_workers": rate_limited_workers,
            "tasks_per_minute": tasks_per_minute,
            "estimated_completion_time": None  # Will be calculated by validator
        }
        return Response(
            content=json.dumps(data, separators=(', ', ':')),
            media_type="application/json"
        )
    except Exception as e:
        logger.error(f"Error getting task stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get task stats: {str(e)}"
        )

@router.get("/{task_id}", response_model=TaskRead)
async def get_task(
    request: Request,
    task_id: int = Path(..., description="Task ID"),
    session: AsyncSession = Depends(get_db)
):
    """Get status and details of a specific task"""
    task_manager = get_task_manager(request)
    task = await task_manager.get_task_status(session, task_id)
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
        task_manager = get_task_manager(request)
        task = await task_manager.get_task_status(session, task_id)
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

@router.post("/queue/start")
async def start_task_queue(request: Request, session: AsyncSession = Depends(get_db)):
    """Start the task queue processor"""
    try:
        # Get task manager from app state
        if not hasattr(request.app.state, 'task_manager'):
            # Initialize task manager if not present
            task_manager = await TaskManager.get_instance(db_manager.async_session)
            request.app.state.task_manager = task_manager
        else:
            task_manager = request.app.state.task_manager

        # Verify worker accounts before starting
        active_workers = await verify_worker_accounts(request, session)
        if not active_workers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active worker accounts available. Please add worker accounts before starting the queue."
            )
            
        # Log task manager and worker status
        logger.info(f"Task manager status: {task_manager.get_status()}")
        logger.info(f"Available workers: {[w.account_no for w in task_manager.available_workers]}")
        logger.info(f"Active workers: {[w.account_no for w in task_manager.active_workers]}")

        # Start queue with verified workers
        if await task_manager.start(session=session):
            # Update app state
            request.app.state.task_queue_running = True

            # Broadcast update
            await request.app.state.connection_manager.broadcast({
                "type": "queue_status",
                "status": "running",
                "message": f"Task queue started with {len(active_workers)} active workers"
            })
            
            return {
                "message": "Task queue started",
                "active_workers": len(active_workers)
            }
        return {"message": "Task queue already running"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting task queue: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start task queue: {str(e)}"
        )

@router.post("/queue/stop")
async def stop_task_queue(request: Request):
    """Stop the task queue processor"""
    try:
        # Get task manager from app state
        if not hasattr(request.app.state, 'task_manager'):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Task manager not initialized"
            )
            
        task_manager = request.app.state.task_manager
        
        # Stop queue
        await task_manager.stop()
        
        # Update app state
        request.app.state.task_queue_running = False
        
        # Broadcast update
        await request.app.state.connection_manager.broadcast({
            "type": "queue_status",
            "status": "stopped",
            "message": "Task queue stopped successfully"
        })
        
        return {"message": "Task queue stopped"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error stopping task queue: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop task queue: {str(e)}"
        )

@router.post("/queue/pause")
async def pause_task_queue(request: Request):
    """Pause the task queue processor"""
    try:
        # Get task manager from app state
        if not hasattr(request.app.state, 'task_manager'):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Task manager not initialized"
            )
            
        task_manager = request.app.state.task_manager
        
        # Pause queue
        if await task_manager.pause():
            # Update app state
            request.app.state.task_queue_running = False
            
            # Broadcast update
            await request.app.state.connection_manager.broadcast({
                "type": "queue_status",
                "status": "paused",
                "message": "Task queue paused successfully"
            })
            
            return {"message": "Task queue paused"}
        return {"message": "Task queue not running"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error pausing task queue: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to pause task queue: {str(e)}"
        )

@router.post("/queue/resume")
async def resume_task_queue(request: Request):
    """Resume the task queue processor"""
    try:
        # Get task manager from app state
        if not hasattr(request.app.state, 'task_manager'):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Task manager not initialized"
            )
            
        task_manager = request.app.state.task_manager
        
        # Resume queue
        if await task_manager.resume():
            # Update app state
            request.app.state.task_queue_running = True
            
            # Broadcast update
            await request.app.state.connection_manager.broadcast({
                "type": "queue_status",
                "status": "running",
                "message": "Task queue resumed successfully"
            })
            
            return {"message": "Task queue resumed"}
        return {"message": "Task queue not paused"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resuming task queue: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resume task queue: {str(e)}"
        )
