from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Dict
import csv
import io
import json
from datetime import datetime

from ..database import get_session
from ..models import Task, Account, Action
from ..schemas.action import (
    ActionRead, ActionImport, ActionCreate, ActionUpdate, 
    ActionStatus, ActionMetadata, ActionType
)
from ..services.task_queue import TaskQueue

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
    """Validate tweet interaction action requirements"""
    # Validate action type
    valid_action_types = ['like_tweet', 'retweet_tweet', 'reply_tweet', 'quote_tweet', 'create_tweet']
    if action_data.task_type not in valid_action_types:
        raise ValueError(f"Invalid action type. Must be one of: {', '.join(valid_action_types)}")
    
    # Check text content requirements
    if action_data.task_type in ['reply_tweet', 'quote_tweet', 'create_tweet']:
        if not action_data.text_content:
            raise ValueError(f"{action_data.task_type} requires text content")
    
    # Check URL requirements
    if action_data.task_type != 'create_tweet':
        if not action_data.source_tweet:
            raise ValueError(f"{action_data.task_type} requires a source tweet URL")
    elif action_data.source_tweet:
        raise ValueError("create_tweet should not have a source tweet URL")

@router.post("/import", response_model=Dict)
async def import_actions(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_session)
):
    """Import actions from CSV file"""
    content = await file.read()
    csv_str = content.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(csv_str))
    
    tasks_created = []
    errors = []
    
    async with db as session:
        for row_idx, row in enumerate(reader, start=1):
            try:
                # Parse CSV row
                action_data = ActionImport(
                    account_no=row["account_no"],
                    task_type=row["task_type"],
                    source_tweet=row["source_tweet"],
                    text_content=row.get("text_content"),
                    media=row.get("media"),
                    priority=int(row.get("priority", 0))
                )
                
                # Validate action requirements
                try:
                    validate_action_requirements(action_data)
                except ValueError as e:
                    errors.append(f"Row {row_idx}: {str(e)}")
                    continue
                
                # Get account
                account = (await session.execute(
                    select(Account).where(Account.account_no == action_data.account_no)
                )).scalar_one_or_none()
                
                if not account:
                    errors.append(f"Row {row_idx}: Account {action_data.account_no} not found")
                    continue
                
                # Extract tweet ID for non-create actions
                tweet_id = None
                if action_data.task_type != 'create_tweet':
                    try:
                        tweet_id = parse_tweet_url(action_data.source_tweet)
                    except ValueError as e:
                        errors.append(f"Row {row_idx}: {str(e)}")
                        continue

                # Prepare meta_data
                meta_data = ActionMetadata(
                    text_content=action_data.text_content,
                    media=action_data.media,
                    priority=action_data.priority,
                    queued_at=datetime.utcnow().isoformat()
                )

                # Use task queue to create and queue the task
                task_queue = TaskQueue(get_session)
                task = await task_queue.add_task(
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
    db: AsyncSession = Depends(get_session)
):
    """Get status of a specific tweet interaction action with associated tweet data"""
    async with db as session:
        # Get action with account relationship
        valid_action_types = ['like_tweet', 'retweet_tweet', 'reply_tweet', 'quote_tweet', 'create_tweet']
        action = (await session.execute(
            select(Action).join(Account).where(
                Action.id == action_id,
                Action.action_type.in_(valid_action_types)
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
    db: AsyncSession = Depends(get_session)
):
    """List tweet interaction actions with optional filters"""
    async with db as session:
        # Only get tweet interaction actions
        valid_action_types = ['like_tweet', 'retweet_tweet', 'reply_tweet', 'quote_tweet', 'create_tweet']
        query = select(Action).where(Action.action_type.in_(valid_action_types))
        
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
                action_dict = {
                    "id": action.id,
                    "action_type": action.action_type,
                    "tweet_url": action.tweet_url,
                    "tweet_id": action.tweet_id,
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
                action_list.append(action_dict)
        
        return action_list

@router.post("/{action_id}/retry", response_model=ActionRead)
async def retry_action(
    action_id: int,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_session)
):
    """Retry a failed tweet interaction action"""
    async with db as session:
        valid_action_types = ['like_tweet', 'retweet_tweet', 'reply_tweet', 'quote_tweet', 'create_tweet']
        action = (await session.execute(
            select(Action).where(
                Action.id == action_id,
                Action.action_type.in_(valid_action_types)
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
        task_queue = TaskQueue(get_session)
        task = await task_queue.add_task(
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
    db: AsyncSession = Depends(get_session)
):
    """Cancel a pending tweet interaction action"""
    async with db as session:
        valid_action_types = ['like_tweet', 'retweet_tweet', 'reply_tweet', 'quote_tweet', 'create_tweet']
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
