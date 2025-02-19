from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..database import get_db
from ..models.settings import SystemSettings
from ..schemas.settings import SystemSettingsUpdate, SystemSettingsResponse

router = APIRouter()

@router.get("/", response_model=SystemSettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)):
    """Get current system settings"""
    try:
        result = await db.execute(select(SystemSettings).limit(1))
        settings = result.scalar_one_or_none()
        
        if not settings:
            # Create default settings if none exist
            settings = SystemSettings()
            db.add(settings)
            await db.commit()
            await db.refresh(settings)
            
        return SystemSettingsResponse(
            max_concurrent_workers=settings.max_concurrent_workers,
            max_requests_per_worker=settings.max_requests_per_worker,
            request_interval=settings.request_interval,
            id=settings.id,
            updated_at=settings.updated_at
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching settings: {str(e)}"
        )

@router.post("/", response_model=SystemSettingsResponse)
async def update_settings(
    settings_update: SystemSettingsUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update system settings"""
    try:
        # Get current settings
        result = await db.execute(select(SystemSettings).limit(1))
        settings = result.scalar_one_or_none()
        
        if not settings:
            settings = SystemSettings()
            db.add(settings)
        
        # Update only provided fields
        if settings_update.max_concurrent_workers is not None:
            if settings_update.max_concurrent_workers < 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="max_concurrent_workers must be at least 1"
                )
            settings.max_concurrent_workers = settings_update.max_concurrent_workers
            
        if settings_update.max_requests_per_worker is not None:
            if settings_update.max_requests_per_worker < 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="max_requests_per_worker must be at least 1"
                )
            settings.max_requests_per_worker = settings_update.max_requests_per_worker
            
        if settings_update.request_interval is not None:
            if settings_update.request_interval < 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="request_interval must be at least 1"
                )
            settings.request_interval = settings_update.request_interval
            
        await db.commit()
        await db.refresh(settings)
        
        return SystemSettingsResponse(
            max_concurrent_workers=settings.max_concurrent_workers,
            max_requests_per_worker=settings.max_requests_per_worker,
            request_interval=settings.request_interval,
            id=settings.id,
            updated_at=settings.updated_at
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating settings: {str(e)}"
        )
