import pytest
import asyncio
import csv
import io
from datetime import datetime
from sqlalchemy import select
from ..models.task import Task
from ..models.account import Account
from ..services.task_manager import TaskManager
from ..schemas.task import TaskType, TaskStatus
from ..database import db_manager

TEST_ACCOUNTS = [
    {
        "account_no": "test_worker_1",
        "act_type": "worker",
        "login": "test_worker1",
        "password": "test123",
        "auth_token": "test_token1",
        "ct0": "test_ct0_1",
        "proxy_url": "proxy1.test.com",
        "proxy_port": "8080",
        "proxy_username": "proxy_user1",
        "proxy_password": "proxy_pass1",
        "user_agent": "Mozilla/5.0 Test Agent 1"
    },
    {
        "account_no": "test_worker_2",
        "act_type": "worker",
        "login": "test_worker2",
        "password": "test123",
        "auth_token": "test_token2",
        "ct0": "test_ct0_2",
        "proxy_url": "proxy2.test.com",
        "proxy_port": "8080",
        "proxy_username": "proxy_user2",
        "proxy_password": "proxy_pass2",
        "user_agent": "Mozilla/5.0 Test Agent 2"
    }
]

TEST_USERNAMES = [
    "user1", "user2", "user3", "user4", "user5",
    "user6", "user7", "user8", "user9", "user10"
]

@pytest.fixture
async def setup_test_accounts(test_db_session):
    """Set up test worker accounts"""
    accounts = []
    for acc_data in TEST_ACCOUNTS:
        account = Account(**acc_data)
        test_db_session.add(account)
        accounts.append(account)
    await test_db_session.commit()
    return accounts

@pytest.fixture
async def task_manager(test_db_session):
    """Create and initialize task manager"""
    manager = await TaskManager.get_instance(test_db_session)
    await manager.initialize()
    await manager.start()
    yield manager
    await manager.stop()

@pytest.mark.asyncio
async def test_profile_scraping(test_db_session, setup_test_accounts, task_manager):
    """Test profile scraping with multiple accounts and tasks"""
    # Create profile scraping tasks
    tasks = []
    for username in TEST_USERNAMES:
        task = await task_manager.add_task(
            test_db_session,
            TaskType.SCRAPE_PROFILE,
            {"username": username},
            priority=len(tasks)  # Different priorities
        )
        tasks.append(task)

    # Wait for tasks to complete (max 30 seconds)
    start_time = datetime.utcnow()
    completed = False
    while not completed and (datetime.utcnow() - start_time).seconds < 30:
        # Check task statuses
        completed = True
        for task in tasks:
            await test_db_session.refresh(task)
            if task.status not in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                completed = False
                break
        if not completed:
            await asyncio.sleep(1)

    # Verify results
    for task in tasks:
        await test_db_session.refresh(task)
        assert task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
        if task.status == TaskStatus.COMPLETED:
            assert task.result is not None
            assert "username" in task.result
            assert "profile_data" in task.result
            profile_data = task.result["profile_data"]
            assert all(key in profile_data for key in ["bio", "profile_url", "profile_image_url"])

@pytest.mark.asyncio
async def test_tweet_scraping(test_db_session, setup_test_accounts, task_manager):
    """Test tweet scraping with multiple accounts and tasks"""
    # Create tweet scraping tasks with different counts
    tasks = []
    for i, username in enumerate(TEST_USERNAMES):
        task = await task_manager.add_task(
            test_db_session,
            TaskType.SCRAPE_TWEETS,
            {
                "username": username,
                "count": (i + 1) * 5  # Different tweet counts
            },
            priority=len(tasks)
        )
        tasks.append(task)

    # Wait for tasks to complete (max 30 seconds)
    start_time = datetime.utcnow()
    completed = False
    while not completed and (datetime.utcnow() - start_time).seconds < 30:
        completed = True
        for task in tasks:
            await test_db_session.refresh(task)
            if task.status not in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                completed = False
                break
        if not completed:
            await asyncio.sleep(1)

    # Verify results
    for i, task in enumerate(tasks):
        await test_db_session.refresh(task)
        assert task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
        if task.status == TaskStatus.COMPLETED:
            assert task.result is not None
            assert "username" in task.result
            assert "tweets" in task.result
            tweets = task.result["tweets"]
            assert isinstance(tweets, list)
            # Verify tweet structure
            for tweet in tweets:
                assert all(key in tweet for key in [
                    "id", "text", "created_at", "metrics"
                ])
                assert all(key in tweet["metrics"] for key in [
                    "like_count", "retweet_count", "reply_count"
                ])

@pytest.mark.asyncio
async def test_rate_limiting(test_db_session, setup_test_accounts, task_manager):
    """Test rate limiting functionality"""
    # Create many tasks to trigger rate limits
    tasks = []
    for i in range(50):  # Create 50 tasks
        task = await task_manager.add_task(
            test_db_session,
            TaskType.SCRAPE_PROFILE,
            {"username": f"test_user_{i}"},
            priority=0
        )
        tasks.append(task)

    # Wait briefly
    await asyncio.sleep(5)

    # Check that some tasks are still pending due to rate limits
    pending_tasks = await test_db_session.execute(
        select(Task).where(Task.status == TaskStatus.PENDING)
    )
    pending_count = len(pending_tasks.scalars().all())
    assert pending_count > 0, "Rate limiting should prevent all tasks from running at once"

@pytest.mark.asyncio
async def test_task_priority(test_db_session, setup_test_accounts, task_manager):
    """Test task priority ordering"""
    # Create tasks with different priorities
    priorities = [0, 5, 10]  # Low, medium, high
    tasks = []
    for priority in priorities:
        task = await task_manager.add_task(
            test_db_session,
            TaskType.SCRAPE_PROFILE,
            {"username": f"priority_test_{priority}"},
            priority=priority
        )
        tasks.append(task)

    # Wait briefly
    await asyncio.sleep(5)

    # Check execution order
    completed_tasks = []
    for task in tasks:
        await test_db_session.refresh(task)
        if task.started_at:
            completed_tasks.append((task.priority, task.started_at))

    # Sort by start time
    completed_tasks.sort(key=lambda x: x[1])
    
    # Higher priority tasks should start first
    priorities_order = [t[0] for t in completed_tasks]
    assert priorities_order == sorted(priorities_order, reverse=True), \
        "Tasks should be executed in priority order"

@pytest.mark.asyncio
async def test_csv_import(test_db_session, setup_test_accounts, task_manager):
    """Test CSV import functionality"""
    # Create test CSV content
    csv_content = "Username\n" + "\n".join(TEST_USERNAMES)
    csv_file = io.StringIO(csv_content)
    csv_reader = csv.DictReader(csv_file)

    # Create tasks from CSV
    tasks = []
    for row in csv_reader:
        username = row['Username'].strip()
        if username:
            task = await task_manager.add_task(
                test_db_session,
                TaskType.SCRAPE_TWEETS,
                {
                    "username": username,
                    "count": 15
                },
                priority=0
            )
            tasks.append(task)

    assert len(tasks) == len(TEST_USERNAMES), \
        "All usernames from CSV should be converted to tasks"

    # Wait for some tasks to complete
    await asyncio.sleep(10)

    # Verify task creation and processing
    for task in tasks:
        await test_db_session.refresh(task)
        assert task.status != TaskStatus.PENDING, \
            "Tasks should start processing"

@pytest.mark.asyncio
async def test_error_handling(test_db_session, setup_test_accounts, task_manager):
    """Test error handling in tasks"""
    # Create task with invalid username
    task = await task_manager.add_task(
        test_db_session,
        TaskType.SCRAPE_PROFILE,
        {"username": ""},  # Invalid username
        priority=0
    )

    # Wait for task to fail
    start_time = datetime.utcnow()
    while (datetime.utcnow() - start_time).seconds < 10:
        await test_db_session.refresh(task)
        if task.status == TaskStatus.FAILED:
            break
        await asyncio.sleep(1)

    assert task.status == TaskStatus.FAILED
    assert task.error is not None
    assert task.retry_count > 0

@pytest.fixture
async def test_db_session():
    """Create a test database session"""
    async_session = db_manager.async_session()
    async with async_session() as session:
        yield session
        # Cleanup
        await session.rollback()
