import pytest
import asyncio
from datetime import datetime
from sqlalchemy import select
from ..models.task import Task
from ..models.account import Account
from ..services.task_queue import TaskQueue
from ..schemas.task import TaskType, TaskStatus
from ..database import get_session

@pytest.mark.asyncio
async def test_task_creation(test_db_session):
    """Test creating a task"""
    # Create a worker account first
    account = Account(
        account_no="test_worker_1",
        act_type="worker",
        login="test_worker",
        password="test123",
        auth_token="test_token",
        ct0="test_ct0"
    )
    test_db_session.add(account)
    await test_db_session.commit()

    # Create task queue
    task_queue = TaskQueue(lambda: test_db_session)

    # Create a task
    task = await task_queue.add_task(
        test_db_session,
        TaskType.SCRAPE_PROFILE,
        {"username": "test_user"},
        priority=1
    )

    assert task.id is not None
    assert task.type == TaskType.SCRAPE_PROFILE
    assert task.status == TaskStatus.PENDING
    assert task.input_params == {"username": "test_user"}
    assert task.priority == 1

@pytest.mark.asyncio
async def test_task_processing(test_db_session):
    """Test task processing workflow"""
    # Create worker account
    account = Account(
        account_no="test_worker_2",
        act_type="worker",
        login="test_worker",
        password="test123",
        auth_token="test_token",
        ct0="test_ct0"
    )
    test_db_session.add(account)
    await test_db_session.commit()

    # Create task queue
    task_queue = TaskQueue(lambda: test_db_session)

    # Create and start task queue
    await task_queue.start()

    # Create a task
    task = await task_queue.add_task(
        test_db_session,
        TaskType.SCRAPE_PROFILE,
        {"username": "test_user"},
        priority=1
    )

    # Wait for task to be processed (max 5 seconds)
    for _ in range(50):
        await asyncio.sleep(0.1)
        await test_db_session.refresh(task)
        if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
            break

    # Stop task queue
    await task_queue.stop()

    assert task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
    if task.status == TaskStatus.COMPLETED:
        assert task.result is not None
    else:
        assert task.error is not None

@pytest.mark.asyncio
async def test_rate_limiting(test_db_session):
    """Test rate limiting functionality"""
    # Create worker account
    account = Account(
        account_no="test_worker_3",
        act_type="worker",
        login="test_worker",
        password="test123",
        auth_token="test_token",
        ct0="test_ct0"
    )
    test_db_session.add(account)
    await test_db_session.commit()

    # Create task queue
    task_queue = TaskQueue(lambda: test_db_session)

    # Create multiple tasks rapidly
    tasks = []
    for i in range(10):
        task = await task_queue.add_task(
            test_db_session,
            TaskType.SCRAPE_PROFILE,
            {"username": f"test_user_{i}"},
            priority=1
        )
        tasks.append(task)

    # Start processing
    await task_queue.start()

    # Wait briefly
    await asyncio.sleep(2)

    # Check rate limits
    stmt = select(Task).where(Task.status == TaskStatus.PENDING)
    result = await test_db_session.execute(stmt)
    pending_tasks = result.scalars().all()

    # Some tasks should still be pending due to rate limiting
    assert len(pending_tasks) > 0

    # Stop task queue
    await task_queue.stop()

@pytest.mark.asyncio
async def test_task_priority(test_db_session):
    """Test task priority ordering"""
    # Create worker account
    account = Account(
        account_no="test_worker_4",
        act_type="worker",
        login="test_worker",
        password="test123",
        auth_token="test_token",
        ct0="test_ct0"
    )
    test_db_session.add(account)
    await test_db_session.commit()

    # Create task queue
    task_queue = TaskQueue(lambda: test_db_session)

    # Create tasks with different priorities
    low_priority = await task_queue.add_task(
        test_db_session,
        TaskType.SCRAPE_PROFILE,
        {"username": "low_priority"},
        priority=0
    )

    high_priority = await task_queue.add_task(
        test_db_session,
        TaskType.SCRAPE_PROFILE,
        {"username": "high_priority"},
        priority=10
    )

    # Start processing
    await task_queue.start()

    # Wait briefly
    await asyncio.sleep(1)

    # Refresh tasks
    await test_db_session.refresh(high_priority)
    await test_db_session.refresh(low_priority)

    # High priority task should be processed first
    assert high_priority.started_at < low_priority.started_at

    # Stop task queue
    await task_queue.stop()

@pytest.fixture
async def test_db_session():
    """Create a test database session"""
    async_session = get_session()
    async with async_session() as session:
        yield session
        # Cleanup
        await session.rollback()
