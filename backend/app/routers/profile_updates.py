import uuid
import csv
import io
import json
import logging
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session
from sqlalchemy import select, insert
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from ..database import get_db, db_manager
from ..models.profile_update import ProfileUpdate
from ..models.account import Account
from ..schemas.profile_update import (
    ProfileUpdateCreate, 
    ProfileUpdateResponse, 
    ProfileUpdateBulkResponse,
    ProfileUpdateCSVRow
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile-updates", tags=["profile-updates"])

@router.post("/upload-csv", response_model=ProfileUpdateBulkResponse)
async def upload_profile_updates_csv(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """Upload a CSV file containing profile updates"""
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    try:
        content = await file.read()
        csv_content = content.decode()
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        
        updates = []
        errors = []

        required_fields = {'account_no'}
        optional_fields = {'name', 'description', 'url', 'location', 'profile_image', 'profile_banner', 'lang', 'login'}
        allowed_fields = required_fields | optional_fields

        # Validate CSV headers
        headers = set(csv_reader.fieldnames)
        if not required_fields.issubset(headers):
            missing = required_fields - headers
            raise HTTPException(
                status_code=400, 
                detail=f"Missing required columns: {', '.join(missing)}"
            )

        for row_num, row in enumerate(csv_reader, start=2):  # Start at 2 to account for header row
            try:
                # Filter out empty values and unknown fields
                filtered_row = {
                    k: v.strip() 
                    for k, v in row.items() 
                    if k in allowed_fields and v and v.strip()
                }

                if 'account_no' not in filtered_row:
                    raise ValueError("account_no is required")

                # Generate UUID for profile update
                update_id = str(uuid.uuid4())
                
                # Create profile update record
                profile_update = ProfileUpdate(
                    id=update_id,
                    account_no=filtered_row['account_no'],
                    name=filtered_row.get('name'),
                    description=filtered_row.get('description'),
                    url=filtered_row.get('url'),
                    location=filtered_row.get('location'),
                    profile_image_path=filtered_row.get('profile_image'),  # CSV field matches task param
                    profile_banner_path=filtered_row.get('profile_banner'),  # CSV field matches task param
                    lang=filtered_row.get('lang'),
                    status='pending',
                    created_at=datetime.utcnow(),
                    meta_data={
                        'source': 'csv_upload',
                        'original_row': row
                    }
                )
                
                db.add(profile_update)
                updates.append(profile_update)

                # Get account by account_no
                account_query = select(Account).where(Account.account_no == profile_update.account_no)
                account_result = await db.execute(account_query)
                account = account_result.scalar_one_or_none()
                
                if not account:
                    raise ValueError(f"Account {profile_update.account_no} not found")

                # Create task parameters
                task_params = {
                    "account_id": account.id,  # Required for using correct account
                    "account_no": profile_update.account_no,
                    "meta_data": {
                        "profile_update_id": profile_update.id,
                        "name": filtered_row.get('name'),
                        "description": filtered_row.get('description'),
                        "url": filtered_row.get('url'),
                        "location": filtered_row.get('location'),
                        "profile_image": filtered_row.get('profile_image'),
                        "profile_banner": filtered_row.get('profile_banner'),
                        "lang": filtered_row.get('lang'),
                        "new_login": filtered_row.get('login')
                    }
                }

                # Log task creation with detailed parameters
                logger.info(f"Creating profile update task for account {account.account_no} (ID: {account.id})")
                logger.info(f"Task parameters: {json.dumps(task_params, indent=2)}")

                # Create task with high priority (1) since it's a user-initiated action
                task_manager = request.app.state.task_manager
                task = await task_manager.add_task(
                    db,
                    task_type="update_profile",
                    input_params=task_params,  # Contains account_id at top level
                    priority=1
                )

                # Log task creation result
                if task:
                    logger.info(f"Successfully created task {task.id} for profile update {profile_update.id}")
                else:
                    raise ValueError(f"Failed to create task for profile update {profile_update.id}")

            except Exception as e:
                errors.append({
                    "row": row_num,
                    "data": row,
                    "error": str(e)
                })
                continue

        if updates:
            try:
                await db.commit()
            except Exception as e:
                await db.rollback()
                raise HTTPException(
                    status_code=500,
                    detail=f"Database error: {str(e)}"
                )

        return ProfileUpdateBulkResponse(
            success=bool(updates),
            message=f"Processed {len(updates)} profile updates" + 
                   (f" with {len(errors)} errors" if errors else ""),
            updates=[ProfileUpdateResponse.from_orm(u) for u in updates],
            errors=errors if errors else None
        )

    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Invalid CSV file encoding. Please ensure the file is UTF-8 encoded."
        )
    except csv.Error as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid CSV format: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing CSV: {str(e)}"
        )

@router.post("/list", response_model=List[ProfileUpdateResponse])
async def list_profile_updates(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    account_no: str = None
):
    """Get list of profile updates with optional filtering"""
    query = select(ProfileUpdate).order_by(ProfileUpdate.id.desc())
    
    if status:
        query = query.where(ProfileUpdate.status == status)
    if account_no:
        query = query.where(ProfileUpdate.account_no == account_no)
        
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    updates = result.scalars().all()
    return updates

@router.post("/get/{profile_update_id}", response_model=ProfileUpdateResponse)
async def get_profile_update(
    profile_update_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific profile update"""
    query = select(ProfileUpdate).where(ProfileUpdate.id == profile_update_id)
    result = await db.execute(query)
    update = result.scalar_one_or_none()
    
    if not update:
        raise HTTPException(
            status_code=404,
            detail="Profile update not found"
        )
    return update

@router.delete("/{profile_update_id}")
async def delete_profile_update(
    profile_update_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete a pending profile update"""
    query = select(ProfileUpdate).where(
        ProfileUpdate.id == profile_update_id,
        ProfileUpdate.status == 'pending'
    )
    result = await db.execute(query)
    update = result.scalar_one_or_none()
    
    if not update:
        raise HTTPException(
            status_code=404,
            detail="Pending profile update not found"
        )
        
    try:
        await db.delete(update)
        await db.commit()
        return {"message": "Profile update deleted successfully"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting profile update: {str(e)}"
        )
