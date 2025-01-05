from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, BackgroundTasks, Query, Response, WebSocket, Request
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
import csv
import io
from datetime import datetime, timedelta
import logging
import asyncio
from urllib.parse import quote

from ..database import get_db
from ..models.account import Account, ValidationState
from ..schemas.account import (
    Account as AccountSchema,
    AccountValidation,
    AccountImportResponse,
    BulkValidationResponse,
    ValidationStatus
)
from ..services.account_validator import validate_account as validate_account_service, validate_accounts_parallel
from ..services.account_recovery import recover_account

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

async def broadcast_message(request: Request, message_type: str, data: dict):
    """Broadcast a message to all connected clients"""
    try:
        message = {
            "type": message_type,
            "timestamp": datetime.utcnow().isoformat(),
            **data
        }
        await request.app.state.connection_manager.broadcast(message)
    except Exception as e:
        logger.error(f"Error broadcasting message: {e}")

@router.get("")  # Root endpoint without slash
@router.get("/")  # Root endpoint with slash
async def list_accounts(
    skip: int = 0,
    limit: int = 100,
    include_deleted: bool = False,
    db: AsyncSession = Depends(get_db)
):
    """List all accounts with pagination"""
    try:
        query = select(Account)
        if not include_deleted:
            query = query.filter(Account.deleted_at == None)
        query = query.offset(skip).limit(limit)
        
        result = await db.execute(query)
        accounts = result.scalars().all()
        return accounts
    except Exception as e:
        logger.error(f"Error listing accounts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.post("/validate/{account_no}")
async def validate_account(
    account_no: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Validate a specific account"""
    try:
        logger.info(f"Starting validation for account {account_no}")
        
        # Get account from database with explicit refresh
        query = select(Account).filter(Account.account_no == account_no)
        result = await db.execute(query)
        account = result.scalar_one_or_none()
        
        if account:
            await db.refresh(account)
        
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found"
            )

        # Check required fields
        required_fields = ['login', 'auth_token', 'ct0', 'proxy_username', 'proxy_password', 'proxy_url', 'proxy_port']
        missing_fields = [field for field in required_fields if not getattr(account, field)]
        if missing_fields:
            error_msg = f"Missing required fields: {', '.join(missing_fields)}"
            logger.error(error_msg)
            return {
                "status": "error",
                "account_no": account_no,
                "validation_result": f"Error: {error_msg}"
            }

        # Update validation status
        account.validation_in_progress = ValidationState.VALIDATING
        await db.commit()

        # Broadcast validation start after commit
        await broadcast_message(request, "task_update", {
            "task_type": "validation",
            "account_no": account_no,
            "status": "validating",
            "message": "Starting validation..."
        })

        # Convert account to dict with proper type handling
        account_dict = {
            'account_no': account.account_no,
            'login': account.login,
            'auth_token': account.auth_token,
            'ct0': account.ct0,
            'user_agent': account.user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'proxy_username': account.proxy_username,
            'proxy_password': account.proxy_password,
            'proxy_url': account.proxy_url,
            'proxy_port': str(account.proxy_port)
        }

        # Perform validation
        logger.info(f"Calling validate_account_service for {account_no}")
        validation_result = await validate_account_service(account_dict)
        logger.info(f"Validation result for {account_no}: {validation_result}")

        # Update account status
        account.last_validation = validation_result
        account.last_validation_time = datetime.utcnow()
        account.validation_in_progress = ValidationState.COMPLETED
        await db.commit()

        # Broadcast completion after commit
        await broadcast_message(request, "task_update", {
            "task_type": "validation",
            "account_no": account_no,
            "status": "completed",
            "validation_result": validation_result,
            "message": f"Validation completed: {validation_result}"
        })

        # Check if account needs recovery
        if any(status in validation_result.lower() for status in ['suspended', 'locked', 'unavailable']):
            await recover_single_account(account_no, db)

        return {
            "status": "success",
            "account_no": account_no,
            "validation_result": validation_result
        }

    except Exception as e:
        logger.error(f"Error validating account {account_no}: {str(e)}", exc_info=True)
        # Try to update account status to failed and broadcast
        try:
            if 'account' in locals():
                account.validation_in_progress = ValidationState.FAILED
                account.last_validation = f"Error: {str(e)}"
                await db.commit()
                
                await broadcast_message(request, "task_update", {
                    "task_type": "validation",
                    "account_no": account_no,
                    "status": "failed",
                    "error": str(e),
                    "message": f"Validation failed: {str(e)}"
                })
        except Exception as inner_e:
            logger.error(f"Error updating failed status: {str(inner_e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.post("/validate-all")
async def validate_all_accounts(
    background_tasks: BackgroundTasks,
    request: Request,
    threads: Optional[int] = Query(6, description="Number of parallel threads to use"),
    db: AsyncSession = Depends(get_db)
):
    """Validate all accounts in parallel"""
    try:
        # Get all accounts that need validation
        result = await db.execute(
            select(Account).filter(Account.deleted_at == None)
        )
        accounts = result.scalars().all()

        if not accounts:
            return {
                "status": "success",
                "message": "No accounts to validate",
                "total": 0
            }

        # Convert accounts to list of dicts
        account_dicts = []
        for account in accounts:
            account_dict = {
                'account_no': account.account_no,
                'login': account.login,
                'auth_token': account.auth_token,
                'ct0': account.ct0,
                'user_agent': account.user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'proxy_username': account.proxy_username,
                'proxy_password': account.proxy_password,
                'proxy_url': account.proxy_url,
                'proxy_port': str(account.proxy_port)
            }
            account_dicts.append(account_dict)

        # Start parallel validation
        async def process_accounts(app=request.app):
            total_accounts = len(accounts)
            completed = 0
            failed = 0
            
            try:
                # Send initial status
                await broadcast_message(request, "bulk_validation", {
                    "status": "started",
                    "total": total_accounts,
                    "completed": 0,
                    "failed": 0,
                    "message": f"Starting validation of {total_accounts} accounts with {threads} threads"
                })
                
                results = await validate_accounts_parallel(account_dicts, threads)
                
                # Update accounts with results and broadcast
                for result in results:
                    try:
                        account = next(acc for acc in accounts if acc.account_no == result['account_no'])
                        account.last_validation = result['status']
                        account.last_validation_time = datetime.utcnow()
                        account.validation_in_progress = ValidationState.COMPLETED
                        
                        # Broadcast individual account update
                        await broadcast_message(request, "task_update", {
                            "task_type": "validation",
                            "account_no": account.account_no,
                            "status": "completed",
                            "validation_result": result['status'],
                            "message": f"Validation completed: {result['status']}"
                        })
                        
                        # Check if account needs recovery
                        if any(status in result['status'].lower() for status in ['suspended', 'locked', 'unavailable']):
                            await recover_single_account(account.account_no, db)
                        
                        completed += 1
                        
                        # Send progress update every 5 accounts or when all are done
                        if completed % 5 == 0 or completed == total_accounts:
                            await broadcast_message(request, "bulk_validation", {
                                "status": "processing",
                                "total": total_accounts,
                                "completed": completed,
                                "failed": failed,
                                "message": f"Validated {completed}/{total_accounts} accounts"
                            })
                            
                    except Exception as e:
                        logger.error(f"Error processing result for account {result['account_no']}: {e}")
                        failed += 1
                
                await db.commit()
                
                # Send completion status
                await broadcast_message(request, "bulk_validation", {
                    "status": "completed",
                    "total": total_accounts,
                    "completed": completed,
                    "failed": failed,
                    "message": f"Validation completed: {completed} successful, {failed} failed"
                })
                
            except Exception as e:
                logger.error(f"Error in parallel validation: {e}")
                # Update accounts to failed state and broadcast
                for account in accounts:
                    try:
                        account.validation_in_progress = ValidationState.FAILED
                        account.last_validation = f"Error: {str(e)}"
                        await broadcast_message(request, "task_update", {
                            "task_type": "validation",
                            "account_no": account.account_no,
                            "status": "failed",
                            "error": str(e),
                            "message": f"Validation failed: {str(e)}"
                        })
                        failed += 1
                    except Exception as inner_e:
                        logger.error(f"Error updating failed status for account {account.account_no}: {inner_e}")
                
                await db.commit()
                
                # Send error status
                await broadcast_message(request, "bulk_validation", {
                    "status": "error",
                    "total": total_accounts,
                    "completed": completed,
                    "failed": failed,
                    "error": str(e),
                    "message": f"Validation failed: {str(e)}"
                })

        # Add task to background tasks with app reference
        background_tasks.add_task(process_accounts, request.app)

        return {
            "status": "success",
            "message": f"Validation started with {threads} parallel threads",
            "total": len(accounts)
        }

    except Exception as e:
        logger.error(f"Error in bulk validation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.post("/recover/{account_no}")
async def recover_single_account(
    account_no: str,
    db: AsyncSession = Depends(get_db)
):
    """Attempt to recover a specific account"""
    try:
        result = await db.execute(
            select(Account).filter(Account.account_no == account_no)
        )
        account = result.scalar_one_or_none()
        
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found"
            )

        # Update recovery status
        account.validation_in_progress = ValidationState.RECOVERING
        account.recovery_attempts += 1
        await db.commit()
        await db.refresh(account)

        # Prepare account dict
        account_dict = {
            'account_no': account.account_no,
            'login': account.login,
            'auth_token': account.auth_token,
            'ct0': account.ct0,
            'user_agent': account.user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'proxy_username': account.proxy_username,
            'proxy_password': account.proxy_password,
            'proxy_url': account.proxy_url,
            'proxy_port': str(account.proxy_port)
        }

        # Prepare proxy config
        proxy_config = {
            'proxytype': 'http',
            'proxyLogin': account.proxy_username,
            'proxyPassword': account.proxy_password,
            'proxyAddress': account.proxy_url,
            'proxyPort': str(account.proxy_port)
        }

        # Attempt recovery
        recovery_result = await recover_account(account_dict, proxy_config)
        
        # Update account status
        account.recovery_status = recovery_result
        account.last_recovery_time = datetime.utcnow()
        account.validation_in_progress = ValidationState.COMPLETED
        await db.commit()

        return {
            "status": "success",
            "account_no": account_no,
            "recovery_result": recovery_result
        }
    except Exception as e:
        logger.error(f"Error recovering account {account_no}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.post("/import", response_model=AccountImportResponse)
async def import_accounts(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """Import accounts from CSV file"""
    total = 0
    successful = 0
    failed = 0
    errors = []
    
    try:
        if not file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No file provided"
            )

        # Check file size (max 10MB)
        MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
        file_size = 0
        content = bytearray()
        
        # Read file in chunks to check size and build content
        chunk_size = 8192  # 8KB chunks for reading
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            file_size += len(chunk)
            if file_size > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="File too large (max 10MB)"
                )
            content.extend(chunk)

        try:
            # Send initial import status
            await broadcast_message(request, "import_status", {
                "status": "started",
                "message": "Starting CSV import",
                "total": 0,
                "successful": 0,
                "failed": 0
            })

            # Process CSV content
            try:
                csv_text = content.decode('utf-8')
            except UnicodeDecodeError:
                # Try with different encodings if UTF-8 fails
                try:
                    csv_text = content.decode('utf-16')
                except UnicodeDecodeError:
                    csv_text = content.decode('latin-1')
            
            csv_file = io.StringIO(csv_text)
            csv_reader = csv.DictReader(csv_file)
            
            # Validate CSV structure
            required_fields = ['account_no', 'login']
            header = csv_reader.fieldnames
            if not header or not all(field in header for field in required_fields):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"CSV must contain required fields: {', '.join(required_fields)}"
                )
            
            # Process in smaller chunks
            CHUNK_SIZE = 50  # Reduced chunk size
            current_chunk = []
            
            for row in csv_reader:
                total += 1
                try:
                    # Clean up the data
                    account_data = {}
                    for k, v in row.items():
                        key = k.strip().lower()
                        if not v or v.strip() == '':
                            account_data[key] = None
                        elif key == 'is_active':
                            account_data[key] = v.strip().lower() == 'true'
                        elif key == 'proxy_port':
                            try:
                                account_data[key] = str(int(float(v.strip())))
                            except (ValueError, TypeError):
                                account_data[key] = v.strip()
                        else:
                            account_data[key] = v.strip()

                    # Set default user agent
                    if not account_data.get('user_agent'):
                        account_data['user_agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    
                    current_chunk.append(account_data)
                    
                    # Process chunk when it reaches CHUNK_SIZE
                    if len(current_chunk) >= CHUNK_SIZE:
                        chunk_success, chunk_errors = await process_account_chunk(db, current_chunk)
                        successful += chunk_success
                        errors.extend(chunk_errors)
                        failed += len(chunk_errors)
                        current_chunk = []  # Reset chunk
                        
                        # Send progress update
                        await broadcast_message(request, "import_status", {
                            "status": "processing",
                            "total": total,
                            "successful": successful,
                            "failed": failed,
                            "message": f"Processing: {successful} successful, {failed} failed out of {total}"
                        })
                        
                except Exception as e:
                    failed += 1
                    errors.append(f"Error processing row {total}: {str(e)}")
                    logger.error(f"Error processing row {total}: {str(e)}")
                    continue
            
            # Process remaining accounts in the last chunk
            if current_chunk:
                chunk_success, chunk_errors = await process_account_chunk(db, current_chunk)
                successful += chunk_success
                errors.extend(chunk_errors)
                failed += len(chunk_errors)

            # Send completion status
            await broadcast_message(request, "import_status", {
                "status": "completed",
                "total": total,
                "successful": successful,
                "failed": failed,
                "message": f"Import completed: {successful} successful, {failed} failed out of {total}",
                "errors": errors[:10] if errors else []
            })

            response = AccountImportResponse(
                total_imported=total,
                successful=successful,
                failed=failed,
                errors=errors[:10]  # Limit number of errors returned
            )
            
            return response

        except Exception as e:
            error_msg = f"Error processing CSV file: {str(e)}"
            logger.error(error_msg)
            
            # Send error status
            await broadcast_message(request, "import_status", {
                "status": "error",
                "message": error_msg,
                "error": str(e),
                "total": total,
                "successful": successful,
                "failed": failed
            })
            
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )

    except HTTPException as e:
        # Send error status for HTTP exceptions
        await request.app.state.connection_manager.broadcast({
            "type": "import_status",
            "status": "error",
            "message": str(e.detail),
            "timestamp": datetime.utcnow().isoformat()
        })
        raise e
    except Exception as e:
        error_msg = f"Unexpected error during import: {str(e)}"
        logger.error(error_msg)
        
        # Send error status
        await request.app.state.connection_manager.broadcast({
            "type": "import_status",
            "status": "error",
            "message": error_msg,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_msg
        )

async def process_account_chunk(db: AsyncSession, accounts: List[dict]) -> tuple[int, List[str]]:
    """Process a chunk of accounts with proper error handling"""
    successful = 0
    errors = []
    
    try:
        for account_data in accounts:
            try:
                # Check if account exists
                result = await db.execute(
                    select(Account).filter(Account.account_no == account_data.get('account_no'))
                )
                existing_account = result.scalar_one_or_none()

                if existing_account:
                    # Update existing account
                    for key, value in account_data.items():
                        if hasattr(existing_account, key):
                            setattr(existing_account, key, value)
                    existing_account.updated_at = datetime.utcnow()
                else:
                    # Create new account
                    account_data['created_at'] = datetime.utcnow()
                    db_account = Account(**account_data)
                    db.add(db_account)
                
                successful += 1
                
            except Exception as e:
                errors.append(f"Error processing account {account_data.get('account_no', 'unknown')}: {str(e)}")
                continue
        
        # Commit chunk
        await db.commit()
        
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database integrity error: {str(e)}")
        errors.append("Database integrity error: Possible duplicate account numbers")
        successful = 0  # Reset successful count for this chunk
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Database error: {str(e)}")
        errors.append(f"Database error: {str(e)}")
        successful = 0  # Reset successful count for this chunk
    
    return successful, errors
