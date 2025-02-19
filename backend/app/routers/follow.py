from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, text, desc, asc, nullslast
from datetime import datetime, timedelta
import csv
import io
import json
import logging
from typing import List, Optional
from ..database import get_db
from ..models.follow_settings import FollowSettings
from ..models.follow_list import FollowList, FollowProgress, ListType
from ..models.account import Account
from ..services.follow_scheduler import FollowScheduler

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/follow", tags=["follow"])

async def get_scheduler(request: Request, response: Response) -> FollowScheduler:
    """Get follow scheduler from app state"""
    try:
        if not hasattr(request.app.state, "follow_scheduler"):
            raise HTTPException(
                status_code=500,
                detail="Follow scheduler not initialized"
            )
        return request.app.state.follow_scheduler
    except Exception as e:
        logger.error(f"Error getting scheduler: {e}")
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get scheduler: {str(e)}"
        )

@router.get("/settings")
async def get_follow_settings(db: AsyncSession = Depends(get_db)):
    """Get current follow system settings"""
    try:
        settings = await db.execute(select(FollowSettings))
        settings = settings.scalar_one_or_none()
        if not settings:
            raise HTTPException(
                status_code=404,
                detail="Follow settings not found"
            )
        return settings
    except Exception as e:
        logger.error(f"Error getting follow settings: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get follow settings: {str(e)}"
        )

@router.post("/settings")
async def update_follow_settings(
    settings: dict,
    db: AsyncSession = Depends(get_db)
):
    """Update follow system settings"""
    try:
        # Get existing settings
        existing = await db.execute(select(FollowSettings))
        existing = existing.scalar_one_or_none()
        
        if not existing:
            # Create new settings if none exist
            existing = FollowSettings(
                max_follows_per_interval=settings.get('max_follows_per_interval', 1),
                interval_minutes=settings.get('interval_minutes', 16),
                max_follows_per_day=settings.get('max_follows_per_day', 30),
                internal_ratio=settings.get('internal_ratio', 5),
                external_ratio=settings.get('external_ratio', 25),
                min_following=settings.get('min_following', 300),
                max_following=settings.get('max_following', 400),
                schedule_groups=settings.get('schedule_groups', 3),
                schedule_hours=settings.get('schedule_hours', 8),
                is_active=settings.get('is_active', False),
                last_updated=datetime.utcnow()
            )
            db.add(existing)
        else:
            # Update existing settings
            for key, value in settings.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            existing.last_updated = datetime.utcnow()
        
        await db.commit()
        return {"message": "Follow settings updated successfully"}
        
    except Exception as e:
        logger.error(f"Error updating follow settings: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update follow settings: {str(e)}"
        )

@router.post("/upload/{list_type}")
async def upload_follow_list(
    list_type: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """Upload a CSV file with usernames to follow"""
    try:
        # Validate list type
        if list_type not in ["internal", "external"]:
            raise HTTPException(400, "Invalid list type. Must be 'internal' or 'external'")
            
        # Read CSV file
        content = await file.read()
        csv_data = content.decode()
        
        # Parse CSV
        usernames = []
        invalid_rows = []
        reader = csv.reader(io.StringIO(csv_data))
        next(reader)  # Skip header row
        
        async with db.begin():
            for i, row in enumerate(reader, 2):  # Start from 2 since we skipped header
                if not row:
                    continue
                    
                username = row[0].strip()
                
                # Basic validation
                if not username:
                    invalid_rows.append(f"Row {i}: Empty username")
                    continue
                    
                if len(username) > 15:
                    invalid_rows.append(f"Row {i}: Username too long")
                    continue

                # For internal lists, verify username exists in Account table
                if list_type == "internal":
                    account = await db.execute(
                        select(Account).where(Account.login == username)
                    )
                    account = account.scalar_one_or_none()
                    if not account:
                        invalid_rows.append(f"Row {i}: Username '{username}' not found in system accounts")
                        logger.warning(f"Internal username '{username}' not found in Account table")
                        continue

                # Check if username already exists in follow list
                existing = await db.execute(
                    select(FollowList).where(FollowList.username == username)
                )
                existing = existing.scalar_one_or_none()
                
                if existing:
                    logger.info(f"Username {username} already exists in follow list")
                    continue
                
                # Add to database within transaction
                follow_list = FollowList(
                    username=username,
                    list_type=ListType.INTERNAL if list_type == "internal" else ListType.EXTERNAL,
                    status="pending",  # Set initial status
                    created_at=datetime.utcnow(),
                    uploaded_by=1,  # Default to admin user ID
                    account_login=username if list_type == "internal" else None  # Set account_login for internal lists
                )
                db.add(follow_list)
                usernames.append(username)
                logger.info(f"Added valid username: {username}")
            
            if invalid_rows:
                logger.error(f"Found invalid rows: {invalid_rows}")
                raise HTTPException(400, f"CSV validation failed: {invalid_rows}")
                
            await db.commit()
            logger.info(f"Successfully added {len(usernames)} {list_type} usernames")
            
            return {
                "message": f"Successfully uploaded {len(usernames)} usernames",
                "type": list_type,
                "usernames": usernames
            }
            
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        logger.error(f"Error processing CSV: {str(e)}")
        await db.rollback()
        raise HTTPException(500, f"Failed to process CSV: {str(e)}")

@router.get("/stats")
async def get_follow_stats(
    db: AsyncSession = Depends(get_db),
    follow_scheduler: FollowScheduler = Depends(get_scheduler)
):
    """Get follow system statistics with pipeline data"""
    try:
        # Get account stats with null handling
        accounts = await db.execute(
            select(
                func.count(Account.id).label('total'),
                func.count(Account.id).filter(
                    and_(
                        Account.following_count.isnot(None),
                        Account.following_count > 0
                    )
                ).label('following'),
                func.count(Account.id).filter(Account.is_active.is_(True)).label('active'),
                func.count(Account.id).filter(
                    and_(
                        Account.rate_limit_until.isnot(None),
                        Account.rate_limit_until > datetime.utcnow()
                    )
                ).label('rate_limited')
            ).select_from(Account)
        )
        account_stats = accounts.first()
        if not account_stats:
            total_accounts = 0
            following_accounts = 0
            active_accounts = 0
            rate_limited_accounts = 0
        else:
            total_accounts = getattr(account_stats, 'total', 0) or 0
            following_accounts = getattr(account_stats, 'following', 0) or 0
            active_accounts = getattr(account_stats, 'active', 0) or 0
            rate_limited_accounts = getattr(account_stats, 'rate_limited', 0) or 0
        
        # Get active accounts with details and better filtering
        active_accounts = await db.execute(
            select(Account).where(
                and_(
                    Account.is_active.is_(True),
                    Account.deleted_at.is_(None),
                    Account.login.isnot(None),  # Must have username
                    Account.auth_token.isnot(None),  # Must have auth token
                    Account.ct0.isnot(None)  # Must have ct0
                )
            )
        )
        active_accounts = active_accounts.scalars().all() or []  # Default to empty list
        
        # Get settings with defaults
        settings = await db.execute(select(FollowSettings))
        settings = settings.scalar_one_or_none()
        if not settings:
            # Return default settings if none exist
            return {
                "total_accounts": 0,
                "accounts_following": 0,
                "active_accounts": 0,
                "rate_limited_accounts": 0,
                "total_internal": 0,
                "total_external": 0,
                "pending_internal": 0,
                "pending_external": 0,
                "follows_today": 0,
                "follows_this_interval": 0,
                "successful_follows": 0,
                "failed_follows": 0,
                "active_group": None,
                "next_group_start": None,
                "system_active_since": None,
                "average_success_rate": 0,
                "average_follows_per_hour": 0,
                "system_status": {
                    "is_active": False,
                    "total_groups": 3,
                    "hours_per_group": 8,
                    "max_follows_per_day": 30,
                    "max_follows_per_interval": 1,
                    "interval_minutes": 16
                },
                "accounts": [],
                "follow_pipeline": []
            }
        
        # Format active accounts for frontend
        accounts_data = []
        for account in active_accounts:
            account_data = {
                "id": account.id,
                "login": account.login,
                "status": "active" if account.is_active else "inactive",
                "is_rate_limited": account.rate_limit_until > datetime.utcnow() if account.rate_limit_until else False,
                "rate_limit_until": account.rate_limit_until.isoformat() if account.rate_limit_until else None,
                "daily_follows": account.daily_follows or 0,
                "following_count": account.following_count or 0,
                "max_follows_per_day": settings.max_follows_per_day if settings else 30,
                "max_following": settings.max_following if settings else 400,
                "last_followed_at": account.last_followed_at.isoformat() if account.last_followed_at else None,
                "group": json.loads(account.meta_data if isinstance(account.meta_data, str) else '{}').get("group") if account.meta_data else None
            }
            accounts_data.append(account_data)
            
        # Get follow pipeline data with SQLite-compatible ordering
        pipeline_data = await db.execute(
            select(FollowList, FollowProgress)
            .outerjoin(
                FollowProgress,
                and_(
                    FollowList.id == FollowProgress.follow_list_id,
                    or_(
                        FollowProgress.status == "pending",
                        FollowProgress.status == "in_progress",
                        FollowProgress.status == "completed"
                    )
                )
            )
            .order_by(
                # Order by status priority
                text("CASE "
                     "WHEN follow_progress.status = 'in_progress' THEN 1 "
                     "WHEN follow_progress.status = 'pending' THEN 2 "
                     "WHEN follow_progress.status = 'completed' THEN 3 "
                     "ELSE 4 END"),
                # Then by scheduled time
                nullslast(asc(FollowProgress.scheduled_for)),
                # Finally by creation time
                desc(FollowList.created_at)
            )
            .limit(50)  # Limit to recent entries for performance
        )
        pipeline_rows = pipeline_data.all()
        
        # Format pipeline data for frontend
        follow_pipeline = []
        for follow_list, progress in pipeline_rows:
            pipeline_entry = {
                "id": follow_list.id,
                "username": follow_list.username,
                "list_type": follow_list.list_type.value,
                "status": progress.status if progress else "pending",
                "assigned_account": progress.account.login if progress and progress.account else None,
                "started_at": progress.started_at.isoformat() if progress and progress.started_at else None,
                "followed_at": progress.followed_at.isoformat() if progress and progress.followed_at else None,
                "scheduled_for": progress.scheduled_for.isoformat() if progress and progress.scheduled_for else None,
                "error": progress.error_message if progress and progress.error_message else None,
                "created_at": progress.created_at.isoformat() if progress and progress.created_at else None,
                "updated_at": progress.updated_at.isoformat() if progress and progress.updated_at else None,
                "group": json.loads(progress.meta_data if isinstance(progress.meta_data, str) else '{}').get("group") if progress and progress.meta_data else None,
                "next_follow": json.loads(progress.meta_data if isinstance(progress.meta_data, str) else '{}').get("next_follow") if progress and progress.meta_data else None
            }
            follow_pipeline.append(pipeline_entry)
        
        # Get follow list stats with SQLite-compatible filtering
        lists = await db.execute(
            select(
                func.count(FollowList.id).filter(
                    and_(
                        FollowList.list_type == ListType.INTERNAL,
                        ~FollowList.id.in_(
                            select(FollowProgress.follow_list_id)
                            .where(FollowProgress.status == "completed")
                            .distinct()
                        )
                    )
                ).label('internal'),
                func.count(FollowList.id).filter(
                    and_(
                        FollowList.list_type == ListType.EXTERNAL,
                        ~FollowList.id.in_(
                            select(FollowProgress.follow_list_id)
                            .where(FollowProgress.status == "completed")
                            .distinct()
                        )
                    )
                ).label('external')
            ).select_from(FollowList)
        )
        list_stats = lists.first()
        if not list_stats:
            internal_count = 0
            external_count = 0
        else:
            internal_count = getattr(list_stats, 'internal', 0) or 0
            external_count = getattr(list_stats, 'external', 0) or 0
        
        # Get pending follows with SQLite-compatible filtering
        pending = await db.execute(
            select(
                func.count(FollowList.id).filter(
                    and_(
                        FollowList.list_type == ListType.INTERNAL,
                        ~FollowList.id.in_(
                            select(FollowProgress.follow_list_id)
                            .where(FollowProgress.status == "completed")
                            .distinct()
                        )
                    )
                ).label('internal_pending'),
                func.count(FollowList.id).filter(
                    and_(
                        FollowList.list_type == ListType.EXTERNAL,
                        ~FollowList.id.in_(
                            select(FollowProgress.follow_list_id)
                            .where(FollowProgress.status == "completed")
                            .distinct()
                        )
                    )
                ).label('external_pending')
            ).select_from(FollowList)
        )
        pending_stats = pending.first()
        if not pending_stats:
            internal_pending = 0
            external_pending = 0
        else:
            internal_pending = getattr(pending_stats, 'internal_pending', 0) or 0
            external_pending = getattr(pending_stats, 'external_pending', 0) or 0
        
        # Get follow progress stats
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        progress = await db.execute(
            select(
                func.count(FollowProgress.id).filter(
                    FollowProgress.followed_at >= today
                ).label('today'),
                func.count(FollowProgress.id).filter(
                    FollowProgress.followed_at >= datetime.utcnow() - timedelta(minutes=15)
                ).label('interval'),
                func.count(FollowProgress.id).filter(
                    FollowProgress.status == "completed"
                ).label('successful'),
                func.count(FollowProgress.id).filter(
                    FollowProgress.status == "failed"
                ).label('failed')
            ).select_from(FollowProgress)
        )
        progress_stats = progress.first()
        
        # Calculate success rate and follows per hour with null checks
        if not progress_stats:
            progress_stats = (0, 0, 0, 0)  # Default values for today, interval, successful, failed
            today_follows = 0
            interval_follows = 0
            successful_follows = 0
            failed_follows = 0
        else:
            today_follows = getattr(progress_stats, 'today', 0) or 0
            interval_follows = getattr(progress_stats, 'interval', 0) or 0
            successful_follows = getattr(progress_stats, 'successful', 0) or 0
            failed_follows = getattr(progress_stats, 'failed', 0) or 0
        
        total_follows = successful_follows + failed_follows
        success_rate = (successful_follows / total_follows * 100) if total_follows > 0 else 0
        
        # Get earliest follow
        earliest_follow = await db.execute(
            select(func.min(FollowProgress.followed_at))
            .where(FollowProgress.status == "completed")
        )
        earliest_follow = earliest_follow.scalar()
        
        if earliest_follow:
            hours_since_start = (datetime.utcnow() - earliest_follow).total_seconds() / 3600
            follows_per_hour = successful_follows / hours_since_start if hours_since_start > 0 else 0
        else:
            follows_per_hour = 0
            
        # Get current group from scheduler
        current_group = await follow_scheduler.get_active_group()
        next_group_start = await follow_scheduler.get_next_group_start()
        
        # Build stats response
        stats = {
            "total_accounts": total_accounts,
            "accounts_following": following_accounts,
            "active_accounts": len(active_accounts),
            "rate_limited_accounts": rate_limited_accounts,
            "total_internal": internal_count,
            "total_external": external_count,
            "pending_internal": internal_pending,
            "pending_external": external_pending,
            "follows_today": today_follows,
            "follows_this_interval": interval_follows,
            "successful_follows": successful_follows,
            "failed_follows": failed_follows,
            "active_group": (current_group + 1) if current_group is not None else None,
            "next_group_start": next_group_start.isoformat() if next_group_start else None,
            "system_active_since": earliest_follow.isoformat() if earliest_follow else None,
            "average_success_rate": round(success_rate, 1),
            "average_follows_per_hour": round(follows_per_hour, 1),
            "system_status": {
                "is_active": settings.is_active if settings else False,
                "total_groups": settings.schedule_groups if settings else 3,
                "hours_per_group": settings.schedule_hours if settings else 8,
                "max_follows_per_day": settings.max_follows_per_day if settings else 30,
                "max_follows_per_interval": settings.max_follows_per_interval if settings else 1,
                "interval_minutes": settings.interval_minutes if settings else 16,
                "active_group": (current_group + 1) if current_group is not None else None,
                "next_group_start": next_group_start.isoformat() if next_group_start else None,
                "current_hour": datetime.utcnow().hour,
                "current_group_start": (
                    datetime.utcnow().replace(
                        hour=(current_group * settings.schedule_hours) % 24 if current_group is not None else 0,
                        minute=0, second=0, microsecond=0
                    ).isoformat() if current_group is not None else None
                )
            },
            "accounts": accounts_data,
            "follow_pipeline": follow_pipeline
        }
        
        logger.info("Generated follow system stats")
        return stats
        
    except Exception as e:
        logger.error(f"Error getting follow stats: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get follow stats: {str(e)}"
        )

@router.post("/start")
async def start_follow_system(
    db: AsyncSession = Depends(get_db),
    follow_scheduler: FollowScheduler = Depends(get_scheduler)
):
    """Start the follow system"""
    try:
        async with db.begin():
            # Get current settings
            settings = await db.execute(select(FollowSettings))
            settings = settings.scalar_one_or_none()
            
            if not settings:
                raise HTTPException(
                    status_code=404,
                    detail="Follow settings not found"
                )
                
            # Verify we have accounts to work with
            accounts_query = select(func.count(Account.id)).where(
                and_(
                    Account.deleted_at.is_(None),
                    Account.auth_token.isnot(None),
                    Account.ct0.isnot(None),
                    Account.login.isnot(None)
                )
            )
            account_count = await db.scalar(accounts_query)
            
            if account_count == 0:
                raise HTTPException(
                    status_code=400,
                    detail="No valid worker accounts found"
                )
                
            # Verify we have usernames to follow
            follow_list_query = select(func.count(FollowList.id))
            follow_list_count = await db.scalar(follow_list_query)
            
            if follow_list_count == 0:
                raise HTTPException(
                    status_code=400,
                    detail="No usernames found in follow list"
                )
                
            # Update settings to activate system
            settings.is_active = True
            settings.last_updated = datetime.utcnow()
            
            # Verify settings are valid
            if settings.schedule_groups <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Schedule groups must be greater than 0"
                )
            
            if settings.schedule_hours <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Schedule hours must be greater than 0"
                )
            
            # Commit transaction before starting scheduler
            await db.commit()
            
        try:
            # Start the scheduler in a separate try block
            await follow_scheduler.start()
            
            return {
                "message": "Follow system started successfully",
                "active_accounts": account_count,
                "follow_list_count": follow_list_count
            }
            
        except Exception as scheduler_error:
            # If scheduler fails, deactivate system
            async with db.begin():
                settings.is_active = False
                settings.last_updated = datetime.utcnow()
                await db.commit()
                
            logger.error(f"Error starting scheduler: {scheduler_error}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to start scheduler: {str(scheduler_error)}"
            )
            
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error starting follow system: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start follow system: {str(e)}"
        )

@router.post("/reconfigure")
async def reconfigure_follow_system(
    db: AsyncSession = Depends(get_db),
    follow_scheduler: FollowScheduler = Depends(get_scheduler)
):
    """Reconfigure the follow system with current settings"""
    try:
        await follow_scheduler.reconfigure()
        return {"message": "Follow system reconfigured successfully"}
    except Exception as e:
        logger.error(f"Error reconfiguring follow system: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reconfigure follow system: {str(e)}"
        )
