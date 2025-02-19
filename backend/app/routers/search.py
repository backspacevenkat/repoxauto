from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, and_
from typing import List, Optional
from datetime import datetime, timedelta
import logging

from ..database import get_db
from ..models.search import TrendingTopic, TopicTweet, SearchedUser
from ..models.task import Task
from ..models.account import Account, ValidationState
from ..schemas.search import (
    TrendingTopicsResponse, TopicTweetsResponse, SearchedUsersResponse,
    SearchRequest, BatchSearchRequest, BatchSearchResponse
)
from ..services.twitter_client import TwitterClient
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["search"])

async def get_available_account(session: AsyncSession, task_type: str) -> Optional[Account]:
    """Get an available account for the given task type"""
    stmt = select(Account).where(
        and_(
            Account.is_active == True,
            Account.is_worker == True,
            Account.auth_token != None,
            Account.ct0 != None,
            Account.deleted_at == None,
            Account.validation_in_progress == ValidationState.COMPLETED
        )
    )
    result = await session.execute(stmt)
    accounts = result.scalars().all()
    
    if not accounts:
        return None
        
    # Prefer worker accounts first, then normal accounts
    worker_accounts = [a for a in accounts if a.act_type == 'worker']
    normal_accounts = [a for a in accounts if a.act_type == 'normal']
    
    return worker_accounts[0] if worker_accounts else normal_accounts[0] if normal_accounts else None

def get_proxy_config(account):
    """Helper function to construct proxy config from account fields"""
    if hasattr(account, 'proxy_url') and hasattr(account, 'proxy_port'):
        return {
            'proxy_url': account.proxy_url,
            'proxy_port': account.proxy_port,
            'proxy_username': getattr(account, 'proxy_username', None),
            'proxy_password': getattr(account, 'proxy_password', None)
        }
    return None

@router.get("/trending")
async def get_trending_topics(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get current trending topics"""
    try:
        logger.info("Getting trending topics")
        account = await get_available_account(db, "search_trending")
        
        if not account:
            raise HTTPException(status_code=503, detail="No available worker accounts")
            
        client = TwitterClient(
            account_no=account.account_no,
            auth_token=account.auth_token,
            ct0=account.ct0,
            proxy_config=get_proxy_config(account)
        )
        
        try:
            # Create task using task manager
            task_manager = request.app.state.task_manager
            task = await task_manager.add_task(
                db,
                "search_trending",
                {},
                priority=1
            )

            try:
                result = await client.get_trending_topics()
                task.status = "completed"
                task.result = result
                await db.commit()
                return {
                    **result,
                    "task_id": task.id
                }
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                await db.commit()
                raise
        finally:
            try:
                await client.close()
            except Exception as e:
                logger.error(f"Error closing client: {str(e)}")

    except Exception as e:
        logger.error(f"Error in trending topics endpoint: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/tweets")
async def search_tweets(
    request: Request,
    search_request: SearchRequest,
    db: AsyncSession = Depends(get_db)
):
    """Search tweets"""
    try:
        logger.info(f"Searching tweets for keyword: {search_request.keyword}")
        account = await get_available_account(db, "search_tweets")
        
        if not account:
            raise HTTPException(status_code=503, detail="No available worker accounts")
            
        client = TwitterClient(
            account_no=account.account_no,
            auth_token=account.auth_token,
            ct0=account.ct0,
            proxy_config=get_proxy_config(account)
        )
        
        try:
            # Create task using task manager
            task_manager = request.app.state.task_manager
            task = await task_manager.add_task(
                db,
                "search_tweets",
                {
                    "keyword": search_request.keyword,
                    "count": search_request.count or 20,
                    "cursor": search_request.cursor
                },
                priority=1
            )

            try:
                result = await client.get_topic_tweets(
                    keyword=search_request.keyword,
                    count=search_request.count or 20,
                    cursor=search_request.cursor
                )
                
                # Sort tweets by view count
                if result.get('tweets'):
                    result['tweets'].sort(
                        key=lambda x: x.get('metrics', {}).get('view_count', 0),
                        reverse=True
                    )
                
                task.status = "completed"
                task.result = result
                await db.commit()
                return {
                    **result,
                    "task_id": task.id
                }
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                await db.commit()
                raise
        finally:
            try:
                await client.close()
            except Exception as e:
                logger.error(f"Error closing client: {str(e)}")

    except Exception as e:
        logger.error(f"Error in tweet search endpoint: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/users")
async def search_users(
    request: Request,
    search_request: SearchRequest,
    db: AsyncSession = Depends(get_db)
):
    """Search users"""
    try:
        logger.info(f"Searching users for keyword: {search_request.keyword}")
        account = await get_available_account(db, "search_users")
        
        if not account:
            raise HTTPException(status_code=503, detail="No available worker accounts")
            
        client = TwitterClient(
            account_no=account.account_no,
            auth_token=account.auth_token,
            ct0=account.ct0,
            proxy_config=get_proxy_config(account)
        )
        
        try:
            # Create task using task manager
            task_manager = request.app.state.task_manager
            task = await task_manager.add_task(
                db,
                "search_users",
                {
                    "keyword": search_request.keyword,
                    "count": search_request.count or 20,
                    "cursor": search_request.cursor
                },
                priority=1
            )

            try:
                result = await client.search_users(
                    keyword=search_request.keyword,
                    count=search_request.count or 20,
                    cursor=search_request.cursor
                )
                
                # Sort users by followers count
                if result.get('users'):
                    result['users'].sort(
                        key=lambda x: x.get('metrics', {}).get('followers_count', 0),
                        reverse=True
                    )
                
                task.status = "completed"
                task.result = result
                await db.commit()
                return {
                    **result,
                    "task_id": task.id
                }
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                await db.commit()
                raise
        finally:
            await client.close()

    except Exception as e:
        logger.error(f"Error in user search endpoint: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/batch")
async def batch_search(
    request: Request,
    batch_request: BatchSearchRequest,
    db: AsyncSession = Depends(get_db)
):
    """Batch search tweets and users"""
    try:
        logger.info(f"Batch searching for keywords: {batch_request.keywords}")
        account = await get_available_account(db, "search_tweets")
        
        if not account:
            raise HTTPException(status_code=503, detail="No available worker accounts")
            
        client = TwitterClient(
            account_no=account.account_no,
            auth_token=account.auth_token,
            ct0=account.ct0,
            proxy_config=get_proxy_config(account)
        )
        
        try:
            # Create task using task manager
            task_manager = request.app.state.task_manager
            task = await task_manager.add_task(
                db,
                "batch_search",
                {
                    "keywords": batch_request.keywords,
                    "count_per_keyword": batch_request.count_per_keyword or 20
                },
                priority=1
            )

            try:
                results = []
                for keyword in batch_request.keywords:
                    # Get tweets
                    tweets_result = await client.get_topic_tweets(
                        keyword=keyword,
                        count=batch_request.count_per_keyword or 20
                    )
                    
                    # Get users
                    users_result = await client.search_users(
                        keyword=keyword,
                        count=batch_request.count_per_keyword or 20
                    )
                    
                    # Sort results
                    if tweets_result.get('tweets'):
                        tweets_result['tweets'].sort(
                            key=lambda x: x.get('metrics', {}).get('view_count', 0),
                            reverse=True
                        )
                    if users_result.get('users'):
                        users_result['users'].sort(
                            key=lambda x: x.get('metrics', {}).get('followers_count', 0),
                            reverse=True
                        )
                    
                    results.append({
                        'keyword': keyword,
                        'tweets': tweets_result,
                        'users': users_result
                    })
                
                result = {
                    'results': results,
                    'timestamp': datetime.utcnow().isoformat()
                }
                
                task.status = "completed"
                task.result = result
                await db.commit()
                return {
                    **result,
                    "task_id": task.id
                }
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                await db.commit()
                raise
        finally:
            await client.close()

    except Exception as e:
        logger.error(f"Error in batch search endpoint: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
