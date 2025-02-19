import logging
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Dict
import csv
import io
import json
from datetime import datetime

from ..database import get_db
from ..models import Task, Account, Action
from ..schemas.action import (
    ActionRead, ActionImport, ActionCreate, ActionUpdate, 
    ActionStatus, ActionMetadata, ActionType, TweetData
)
from ..services.twitter_client import TwitterClient

logger = logging.getLogger(__name__)

router = APIRouter()

def parse_tweet_url(url: str) -> str:
    """Extract tweet ID from URL"""
    try:
        # Handle both x.com and twitter.com URLs
        if '/status/' not in url:
            raise ValueError("Invalid tweet URL format")
        return url.split('/status/')[-1].split('?')[0]
    except Exception as e:
        raise ValueError(f"Could not parse tweet URL: {str(e)}")

def validate_action_requirements(action_data: ActionImport) -> None:
    """Validate action requirements"""
    # All validation is handled by the ActionImport schema validators
    # The schema already maps 'follow' to 'follow_user' and validates requirements
    pass

@router.post("/import", response_model=Dict)
async def import_actions(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db)
):
    """Import actions from CSV file"""
    content = await file.read()
    csv_str = content.decode("utf-8", errors="ignore")
    csv_io = io.StringIO(csv_str)
    reader = csv.DictReader(csv_io)
    
    # Validate CSV headers
    headers = reader.fieldnames
    if not headers:
        return {
            "message": "CSV file is empty or invalid",
            "tasks_created": 0,
            "errors": ["No headers found in CSV file"]
        }

    # Check first row to determine action type
    first_row = next(reader)
    csv_io.seek(0)  # Reset to start
    next(reader)  # Skip header again
    
    # Determine required headers based on action type
    task_type = first_row.get("task_type", "").lower().strip()
    if task_type in ["follow", "follow_user", "f"]:
        required_headers = ["account_no", "task_type", "user"]
    elif task_type in ["dm"]:
        required_headers = ["account_no", "task_type", "text_content", "user"]
    else:
        required_headers = ["account_no", "task_type", "source_tweet"]
    
    missing_headers = [h for h in required_headers if h not in headers]
    if missing_headers:
        return {
            "message": "Missing required columns",
            "tasks_created": 0,
            "errors": [f"Missing required columns for {task_type} action: {', '.join(missing_headers)}"]
        }
        
    # Reset file pointer to start
    csv_io.seek(0)
    next(reader)  # Skip header row

    tasks_created = []
    errors = []
    
    async with db as session:
        for row_idx, row in enumerate(reader, start=1):
            logger.info(f"Processing row {row_idx}: {row}")  # Log each row for debugging
            try:
                # Parse CSV row
                try:
                    task_type = row["task_type"].lower().strip()
                    # For follow actions, only require account_no, task_type, and user
                    if task_type in ["follow", "follow_user", "f"]:
                        action_data = ActionImport(
                            account_no=row["account_no"],
                            task_type=row["task_type"],
                            source_tweet="",  # Empty string for follow actions
                            user=row["user"],  # Required for follow actions
                            api_method=row.get("api_method", "graphql"),
                            priority=int(row.get("priority", 0))
                        )
                    # For DM actions, require account_no, task_type, text_content, and user
                    elif task_type in ["dm"]:
                        action_data = ActionImport(
                            account_no=row["account_no"],
                            task_type=row["task_type"],
                            source_tweet="",  # Empty string for DM actions
                            text_content=row["text_content"],  # Required for DM actions
                            user=row["user"],  # Required for DM actions
                            media=row.get("media"),  # Optional media
                            api_method="rest",  # Always use REST API for DMs
                            priority=int(row.get("priority", 0))
                        )
                    else:
                        # For tweet actions, require source_tweet
                        action_data = ActionImport(
                            account_no=row["account_no"],
                            task_type=row["task_type"],
                            source_tweet=row["source_tweet"],
                            text_content=row.get("text_content"),
                            media=row.get("media"),
                            api_method=row.get("api_method", "graphql"),
                            priority=int(row.get("priority", 0))
                        )
                except KeyError as e:
                    errors.append(f"Row {row_idx}: Missing required field: {str(e)}")
                    continue
                
                # Validate action requirements
                try:
                    validate_action_requirements(action_data)
                except ValueError as e:
                    errors.append(f"Row {row_idx}: {str(e)}")
                    continue
                
                # Get account
                account = (await session.execute(
                    select(Account).where(
                        and_(
                            Account.account_no == action_data.account_no,
                            Account.deleted_at.is_(None)
                        )
                    )
                )).scalar_one_or_none()
                
                if not account:
                    errors.append(f"Row {row_idx}: Account {action_data.account_no} not found")
                    continue

                # Handle follow and DM actions differently
                if action_data.task_type in ['follow_user', 'send_dm']:
                    # Validate required fields
                    if not action_data.user:
                        errors.append(f"Row {row_idx}: user field is required for {action_data.task_type} actions")
                        continue
                    
                    if action_data.task_type == 'send_dm' and not action_data.text_content:
                        errors.append(f"Row {row_idx}: text_content is required for DM actions")
                        continue
                        
                    # Prepare meta_data for follow/DM action
                    meta_data = ActionMetadata(
                        user=action_data.user,
                        text_content=action_data.text_content,
                        media=action_data.media,
                        priority=action_data.priority,
                        queued_at=datetime.utcnow().isoformat()
                    )
                    
                    # Create follow task
                    task_manager = request.app.state.task_manager
                    task = await task_manager.add_task(
                        session,
                        action_data.task_type,
                        {
                            "account_id": account.id,
                            "meta_data": meta_data.dict(exclude_none=True)
                        },
                        priority=action_data.priority
                    )
                else:
                    # Handle tweet-based actions
                    tweet_id = None
                    try:
                        tweet_id = parse_tweet_url(action_data.source_tweet)
                    except ValueError as e:
                        errors.append(f"Row {row_idx}: {str(e)}")
                        continue

                    # Prepare meta_data for tweet action
                    meta_data = ActionMetadata(
                        text_content=action_data.text_content,
                        media=action_data.media,
                        priority=action_data.priority,
                        queued_at=datetime.utcnow().isoformat()
                    )

                    # Create tweet action task
                    task_manager = request.app.state.task_manager
                    task = await task_manager.add_task(
                        session,
                        action_data.task_type,
                        {
                            "account_id": account.id,
                            "tweet_url": action_data.source_tweet,
                            "tweet_id": tweet_id,
                            "meta_data": meta_data.dict(exclude_none=True)
                        },
                        priority=action_data.priority
                    )
                
                if task:
                    tasks_created.append(task)

            except Exception as e:
                errors.append(f"Row {row_idx}: Unexpected error: {str(e)}")
                continue

        await session.commit()

    return {
        "message": "Actions import completed",
        "tasks_created": len(tasks_created),
        "task_ids": [t.id for t in tasks_created],
        "errors": errors
    }

@router.get("/status/{action_id}", response_model=ActionStatus)
async def get_action_status(
    action_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get status of a specific tweet interaction action with associated tweet data"""
    async with db as session:
        # Get action with account relationship
        valid_action_types = ['like_tweet', 'retweet_tweet', 'reply_tweet', 'quote_tweet', 'create_tweet', 'follow_user', 'send_dm']
        action = (await session.execute(
            select(Action).join(Account).where(
                and_(
                    Action.id == action_id,
                    Action.action_type.in_(valid_action_types),
                    Account.deleted_at.is_(None)
                )
            )
        )).scalar_one_or_none()
        
        if not action:
            raise HTTPException(status_code=404, detail="Tweet interaction action not found")
        
        # Get account credentials
        account = action.account
        if not account:
            raise HTTPException(status_code=404, detail="Associated account not found")
        
        # Initialize Twitter client
        client = TwitterClient(
            account_no=account.account_no,
            auth_token=account.auth_token,
            ct0=account.ct0,
            proxy_config=account.proxy_config if account.proxy_config else None
        )
        
        try:
            # Get source tweet data if available
            source_tweet = None
            if action.tweet_id:
                try:
                    tweet_data = await client._process_tweet_data({
                        'rest_id': action.tweet_id,
                        'legacy': action.meta_data.get('source_tweet_data', {})
                    })
                    if tweet_data:
                        source_tweet = TweetData(
                            id=tweet_data['id'],
                            text=tweet_data['text'],
                            author=tweet_data['author'],
                            created_at=tweet_data['created_at'],
                            media=tweet_data.get('media'),
                            metrics=tweet_data.get('metrics'),
                            urls=tweet_data.get('urls'),
                            tweet_url=tweet_data['tweet_url']
                        )
                except Exception as e:
                    logger.error(f"Error getting source tweet data: {str(e)}")
            
            # Get result tweet data for completed actions
            result_tweet = None
            if action.status == 'completed' and action.meta_data and 'result_tweet_data' in action.meta_data:
                try:
                    tweet_data = await client._process_tweet_data({
                        'rest_id': action.meta_data.get('result_tweet_id'),
                        'legacy': action.meta_data.get('result_tweet_data', {})
                    })
                    if tweet_data:
                        result_tweet = TweetData(
                            id=tweet_data['id'],
                            text=tweet_data['text'],
                            author=tweet_data['author'],
                            created_at=tweet_data['created_at'],
                            media=tweet_data.get('media'),
                            metrics=tweet_data.get('metrics'),
                            urls=tweet_data.get('urls'),
                            tweet_url=tweet_data['tweet_url']
                        )
                except Exception as e:
                    logger.error(f"Error getting result tweet data: {str(e)}")
            
            # Get content and media for replies/quotes
            content = None
            media = None
            if action.action_type in ['reply_tweet', 'quote_tweet', 'create_tweet']:
                content = action.meta_data.get('text_content') if action.meta_data else None
                media = action.meta_data.get('media') if action.meta_data else None
            
            return ActionStatus(
                id=action.id,
                status=action.status,
                type=action.action_type,
                tweet_id=action.tweet_id,
                created_at=action.created_at,
                executed_at=action.executed_at,
                error=action.error_message,
                metadata=ActionMetadata(**action.meta_data) if action.meta_data else None,
                rate_limit_info={
                    "reset": action.rate_limit_reset,
                    "remaining": action.rate_limit_remaining
                } if action.rate_limit_reset or action.rate_limit_remaining else None,
                source_tweet=source_tweet,
                content=content,
                media=media,
                result_tweet=result_tweet
            )
        finally:
            await client.close()

@router.get("/list", response_model=List[Dict])
async def list_actions(
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    action_type: str = None,
    db: AsyncSession = Depends(get_db)
):
    """List tweet interaction actions with optional filters"""
    async with db as session:
        # Get all valid action types
        valid_action_types = ['like_tweet', 'retweet_tweet', 'reply_tweet', 'quote_tweet', 'create_tweet', 'follow_user', 'send_dm']
        query = select(Action).join(Account).where(
            and_(
                Action.action_type.in_(valid_action_types),
                Account.deleted_at.is_(None)
            )
        )
        
        if status:
            query = query.where(Action.status == status)
        if action_type:
            query = query.where(Action.action_type == action_type)
        
        query = query.order_by(Action.created_at.desc()).offset(skip).limit(limit)
        result = await session.execute(query)
        actions = result.scalars().all()
        
        # Convert actions to dictionary format
        action_list = []
        for action in actions:
            if action.action_type in valid_action_types:
                # Extract result tweet URL from meta_data
                result_tweet_url = None
                if action.meta_data and 'result' in action.meta_data:
                    result = action.meta_data['result']
                    if isinstance(result, dict):
                        if 'tweet_id' in result:
                            # For reply and quote tweets, construct URL using account and tweet ID
                            if action.action_type in ['reply_tweet', 'quote_tweet']:
                                account = await session.get(Account, action.account_id)
                                if account and result.get('tweet_id'):
                                    result_tweet_url = f"https://twitter.com/{account.username}/status/{result['tweet_id']}"
                        elif 'tweet_url' in result:
                            result_tweet_url = result['tweet_url']

                # Build base action dict
                action_dict = {
                    "id": action.id,
                    "action_type": action.action_type,
                    "tweet_url": action.tweet_url if action.action_type not in ['follow_user', 'send_dm'] else None,
                    "tweet_id": action.tweet_id if action.action_type not in ['follow_user', 'send_dm'] else None,
                    "account_id": action.account_id,
                    "task_id": action.task_id,
                    "status": action.status,
                    "error_message": action.error_message,
                    "created_at": action.created_at.isoformat() if action.created_at else None,
                    "executed_at": action.executed_at.isoformat() if action.executed_at else None,
                    "rate_limit_reset": action.rate_limit_reset.isoformat() if action.rate_limit_reset else None,
                    "rate_limit_remaining": action.rate_limit_remaining,
                    "meta_data": action.meta_data
                }

                # Add tweet-specific fields for tweet actions
                if action.action_type not in ['follow_user', 'send_dm']:
                    action_dict["result_tweet_url"] = result_tweet_url
                    # Update status for reply/quote tweets that have a result
                    action_dict["status"] = "completed" if result_tweet_url and action.action_type in ['reply_tweet', 'quote_tweet'] else action.status
                action_list.append(action_dict)
        
        return action_list

@router.post("/{action_id}/retry", response_model=ActionRead)
async def retry_action(
    action_id: int,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db)
):
    """Retry a failed tweet interaction action"""
    async with db as session:
        valid_action_types = ['like_tweet', 'retweet_tweet', 'reply_tweet', 'quote_tweet', 'create_tweet', 'follow_user', 'send_dm']
        action = (await session.execute(
            select(Action).join(Account).where(
                and_(
                    Action.id == action_id,
                    Action.action_type.in_(valid_action_types),
                    Account.deleted_at.is_(None)
                )
            )
        )).scalar_one_or_none()
        
        if not action:
            raise HTTPException(status_code=404, detail="Tweet interaction action not found")
        
        if action.status != "failed":
            raise HTTPException(status_code=400, detail="Can only retry failed actions")
        
        # Update meta_data for retry
        meta_data = action.meta_data or {}
        meta_data.update({
            "retry_of": action.id,
            "retry_count": meta_data.get("retry_count", 0) + 1,
            "queued_at": datetime.utcnow().isoformat()
        })
        
        # Use task queue to create and queue the retry task
        task_manager = request.app.state.task_manager
        task = await task_manager.add_task(
            session,
            action.action_type,
            {
                "account_id": action.account_id,
                "tweet_url": action.tweet_url,
                "tweet_id": action.tweet_id,
                "meta_data": meta_data
            },
            priority=meta_data.get("priority", 0)
        )
        
        return action

@router.post("/{action_id}/cancel", response_model=ActionRead)
async def cancel_action(
    action_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Cancel a pending tweet interaction action"""
    async with db as session:
        valid_action_types = ['like_tweet', 'retweet_tweet', 'reply_tweet', 'quote_tweet', 'create_tweet', 'follow_user', 'send_dm']
        action = (await session.execute(
            select(Action).where(
                Action.id == action_id,
                Action.action_type.in_(valid_action_types)
            )
        )).scalar_one_or_none()
        
        if not action:
            raise HTTPException(status_code=404, detail="Tweet interaction action not found")
        
        if action.status != "pending":
            raise HTTPException(status_code=400, detail="Can only cancel pending actions")
        
        action.status = "cancelled"
        action.executed_at = datetime.utcnow()
        
        await session.commit()
        
        return action
