from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, BackgroundTasks, Query, Response, Request, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError
from typing import List, Optional, Dict, Any
import csv
import io
import json
import aiofiles
from datetime import datetime
import logging
import asyncio
import pandas as pd
from filelock import FileLock
from urllib.parse import quote, urljoin, urlparse, urlencode, parse_qsl
import os
from typing import List, Optional, Dict, Any, Tuple
from ..database import get_db, safe_commit, db_manager
from ..models.account import Account, ValidationState
from ..services.twitter_client import construct_proxy_url
from ..schemas.account import (
    AccountImportResponse
)
from ..services.oauth_setup import OAuthSetupService
from ..services.password_manager import PasswordManager
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

# Constants
ACCOUNTS_FILE = 'accounts6.csv'
BACKUP_DIR = 'backups'
os.makedirs(BACKUP_DIR, exist_ok=True)

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

async def create_backup(account_no: str, db: AsyncSession) -> str:
    """Create a backup of the account data with database state"""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = os.path.join(BACKUP_DIR, f"account_{account_no}_{timestamp}.bak")
        
        # Get account data from database
        query = select(Account).filter(Account.account_no == account_no)
        result = await db.execute(query)
        account = result.scalar_one_or_none()
        
        if account:
            # Convert account to dict
            account_dict = {
                col.name: getattr(account, col.name)
                for col in Account.__table__.columns
            }
            
            # Save backup with both database and file state
            backup_data = {
                'database_state': account_dict,
                'timestamp': timestamp,
                'account_no': account_no
            }
            
            # Save as JSON for better structure preservation
            async with aiofiles.open(backup_file, 'w') as f:
                await f.write(json.dumps(backup_data, default=str, indent=2))
            
            logger.info(f"Created backup at {backup_file}")
            return backup_file
        return ""
    except Exception as e:
        logger.error(f"Error creating backup: {str(e)}")
        return ""

@asynccontextmanager
async def get_task_db():
    """Get a new database session for task processing"""
    session = db_manager.async_session()
    try:
        yield session
    finally:
        await session.close()

@router.post("/import")
async def import_accounts(
    file: UploadFile = File(...),
    threads: int = Form(6),
    db: AsyncSession = Depends(get_db)
):
    """Import accounts from CSV file"""
    try:
        # Read CSV file
        contents = await file.read()
        df = pd.read_csv(io.StringIO(contents.decode('utf-8-sig')))
        
        successful = 0
        failed = 0
        errors = []
        
        # Process each row
        for _, row in df.iterrows():
            try:
                # Convert row to dict and clean NaN values
                account_data = {
                    k: v for k, v in row.to_dict().items() 
                    if pd.notna(v) and v != ''
                }
                
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
                    
                    # Set worker flag based on act_type
                    if account_data.get('act_type') == 'worker':
                        existing_account.is_worker = True
                    else:
                        existing_account.is_worker = False
                    
                    existing_account.is_active = True
                    existing_account.oauth_setup_status = 'PENDING'
                    
                else:
                    # Create new account
                    account_data['created_at'] = datetime.utcnow()
                    account_data['updated_at'] = datetime.utcnow()
                    
                    # Set worker flag based on act_type from CSV
                    account_data['is_worker'] = account_data.get('act_type') == 'worker'
                    account_data['is_active'] = True
                    account_data['oauth_setup_status'] = 'PENDING'
                    
                    # Create new Account instance
                    db_account = Account(**account_data)
                    db.add(db_account)
                
                successful += 1
                
            except Exception as e:
                failed += 1
                errors.append(f"Error processing account {account_data.get('account_no', 'unknown')}: {str(e)}")
                logger.error(f"Import error: {str(e)}")
                continue
        
        try:
            # Commit changes
            await db.commit()
            logger.info(f"Successfully imported {successful} accounts, {failed} failed")
        except Exception as e:
            await db.rollback()
            logger.error(f"Error committing changes: {str(e)}")
            raise
        
        return {
            "total_imported": successful + failed,
            "successful": successful,
            "failed": failed,
            "errors": errors
        }
        
    except Exception as e:
        logger.error(f"Error in import_accounts: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Error importing accounts: {str(e)}"
        )

@router.post("/oauth/bulk")
async def start_oauth_setup(
    request: Request,
    threads: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Start OAuth setup for multiple accounts in parallel using a worker queue"""
    try:
        # Get accounts and thread count from request body
        body = await request.json()
        account_numbers = body.get('accounts', [])
        
        # Use thread count from query param first, then body, then default
        num_threads = threads if threads is not None else body.get('threads', 6)
        
        # Validate thread count
        if not 1 <= num_threads <= 12:
            num_threads = 6  # Reset to default if invalid
        
        if not account_numbers:
            raise ValueError("No accounts provided")

        # Ensure all account numbers are strings
        account_numbers = [str(acc) for acc in account_numbers if acc]
        
        if not account_numbers:
            raise ValueError("No valid account numbers provided")

        logger.info(f"Processing OAuth setup for accounts: {account_numbers} with {num_threads} threads")
        
        # Create semaphore for parallel processing
        semaphore = asyncio.Semaphore(num_threads)
        
        # Get accounts from database to check credentials
        result = await db.execute(
            select(Account).filter(Account.account_no.in_(account_numbers))
        )
        accounts = result.scalars().all()

        # Track results
        successful = []
        failed = []
        skipped = []
        results_lock = asyncio.Lock()

        # Create queue and add only accounts that need OAuth setup
        queue = asyncio.Queue()
        from ..services.oauth_setup import has_all_oauth_credentials

        for account in accounts:
            if has_all_oauth_credentials({
                'consumer_key': account.consumer_key,
                'consumer_secret': account.consumer_secret,
                'bearer_token': account.bearer_token,
                'access_token': account.access_token,
                'access_token_secret': account.access_token_secret,
                'client_id': account.client_id,
                'client_secret': account.client_secret
            }):
                logger.info(f"Account {account.account_no} already has all OAuth credentials")
                skipped.append(account.account_no)
                successful.append(account.account_no)  # Count as successful since it's already done
                await broadcast_message(request, "oauth_status", {
                    "type": "oauth_status",
                    "account_no": account.account_no,
                    "status": "completed",
                    "message": "OAuth credentials already exist"
                })
            else:
                await queue.put(account.account_no)
        
        # Worker function to process accounts
        async def worker(worker_id: int):
            while True:
                try:
                    # Try to get next account from queue with timeout
                    try:
                        acc_no = await asyncio.wait_for(queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        # No more accounts to process
                        break
                        
                    try:
                        # Process account with its own database session
                        async with get_task_db() as task_db:
                            result = await process_account(acc_no, task_db, semaphore, request)
                            
                        # Update results thread-safely
                        async with results_lock:
                            if isinstance(result, dict) and result.get('status') == 'success':
                                successful.append(acc_no)
                            else:
                                failed.append(acc_no)
                                logger.error(f"Failed to process account {acc_no}")
                                
                    except Exception as e:
                        logger.error(f"Error processing account {acc_no}: {str(e)}")
                        async with results_lock:
                            failed.append(acc_no)
                    finally:
                        queue.task_done()
                        
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Worker {worker_id} error: {str(e)}")
                    continue
        
        # Start limited number of workers
        workers = [
            asyncio.create_task(worker(i))
            for i in range(num_threads)
        ]
        
        # Wait for all accounts to be processed
        await queue.join()
        
        # Cancel and clean up workers
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        
        return {
            "status": "completed",
            "successful": successful,
            "failed": failed,
            "skipped": skipped,
            "message": f"Processed {len(successful)} accounts successfully ({len(skipped)} skipped), {len(failed)} failed"
        }
        
    except ValueError as ve:
        logger.error(f"Validation error: {str(ve)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        logger.error(f"Error in OAuth setup: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

async def process_account(account_no: str, db: AsyncSession, semaphore: asyncio.Semaphore, request: Request):
    try:
        logger.info(f"Starting OAuth setup for account {account_no}")
        
        # Create backup before starting
        backup_file = await create_backup(account_no, db)
        if backup_file:
            logger.info(f"Created backup at {backup_file}")
            await broadcast_message(request, "oauth_status", {
                "type": "oauth_status",
                "account_no": account_no,
                "status": "backup_created",
                "message": f"Created backup at {backup_file}"
            })
        
        # Get account from database with explicit refresh and locking
        query = select(Account).filter(Account.account_no == account_no).with_for_update()
        result = await db.execute(query)
        account = result.scalar_one_or_none()
        
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found"
            )
            
        await db.refresh(account)

        # Check if account is already being processed
        if account.validation_in_progress == ValidationState.VALIDATING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Account is already being processed"
            )

        # Check if all OAuth credentials already exist
        from ..services.oauth_setup import has_all_oauth_credentials
        if has_all_oauth_credentials({
            'consumer_key': account.consumer_key,
            'consumer_secret': account.consumer_secret,
            'bearer_token': account.bearer_token,
            'access_token': account.access_token,
            'access_token_secret': account.access_token_secret,
            'client_id': account.client_id,
            'client_secret': account.client_secret
        }):
            logger.info(f"Account {account_no} already has all OAuth credentials")
            await broadcast_message(request, "oauth_status", {
                "type": "oauth_status",
                "account_no": account_no,
                "status": "completed",
                "message": "OAuth credentials already exist"
            })
            return {
                "status": "success",
                "account_no": account_no,
                "message": "OAuth credentials already exist"
            }

        # Check required fields
        required_fields = ['login', 'auth_token', 'ct0', 'proxy_username', 'proxy_password', 'proxy_url', 'proxy_port']
        missing_fields = [field for field in required_fields if not getattr(account, field)]
        if missing_fields:
            error_msg = f"Missing required fields: {', '.join(missing_fields)}"
            logger.error(error_msg)
            await broadcast_message(request, "oauth_status", {
                "type": "oauth_status",
                "account_no": account_no,
                "status": "error",
                "message": error_msg
            })
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )

        # Update status
        account.validation_in_progress = ValidationState.VALIDATING
        if not await safe_commit(db):
            logger.error("Failed to update validation status")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update validation status"
            )

        # Broadcast start
        await broadcast_message(request, "oauth_status", {
            "type": "oauth_status",
            "account_no": account_no,
            "status": "started",
            "message": "Starting OAuth setup..."
        })

        # Validate and construct proxy URL with enhanced error handling
        # Validate proxy components
        if not all([
            account.proxy_username,
            account.proxy_password,
            account.proxy_url,
            account.proxy_port
        ]):
            missing = []
            if not account.proxy_username: missing.append('proxy_username')
            if not account.proxy_password: missing.append('proxy_password')
            if not account.proxy_url: missing.append('proxy_url')
            if not account.proxy_port: missing.append('proxy_port')
            
            error_msg = f"Missing proxy configuration: {', '.join(missing)}"
            logger.error(error_msg)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )

        # Validate proxy port
        try:
            proxy_port = str(int(account.proxy_port))  # Ensure valid integer
            if not (1 <= int(proxy_port) <= 65535):
                raise ValueError(f"Invalid port number: {proxy_port}")
        except (ValueError, TypeError) as e:
            error_msg = f"Invalid proxy port: {str(e)}"
            logger.error(error_msg)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )

        # Construct proxy URL with validated components
        try:
            proxy_url = construct_proxy_url(
                str(account.proxy_username),
                str(account.proxy_password),
                str(account.proxy_url),
                proxy_port
            )
            logger.info(f"Successfully constructed proxy URL for account {account_no}")
        except Exception as e:
            error_msg = f"Failed to construct proxy URL: {str(e)}"
            logger.error(error_msg)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )

        # Convert account to dict with validated fields
        account_dict = {
            'account_no': account.account_no,
            'login': account.login,
            'auth_token': account.auth_token,
            'ct0': account.ct0,
            'two_fa': account.two_fa, 
            'user_agent': account.user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'proxy_username': str(account.proxy_username),
            'proxy_password': str(account.proxy_password),
            'proxy_url': str(account.proxy_url),
            'proxy_port': proxy_port,
            'two_fa': account.two_fa,
            'password': account.password,
            'encoded_proxy_url': proxy_url
        }
        
        # Log proxy configuration (excluding credentials)
        masked_url = proxy_url.replace(str(account.proxy_password), '***')
        logger.info(f"Proxy configuration for account {account_no}: {masked_url}")
        
        # Log proxy configuration for debugging (excluding credentials)
        logger.debug(f"Configured proxy server: http://{account.proxy_url}:{account.proxy_port}")
        logger.debug(f"Using encoded proxy URL: {proxy_url.replace(str(account.proxy_password), '***')}")

        # Log account details for debugging
        logger.debug(f"Account details for OAuth setup: {account_dict}")

        # Use semaphore to control entire browser lifecycle
        async with semaphore:
            # Initialize OAuth setup service with retries
            oauth_service = None
            for attempt in range(3):  # Try up to 3 times
                try:
                    # First validate proxy configuration
                    logger.info(f"Validating proxy configuration for account {account_no} (attempt {attempt + 1})")
                    
                    # Verify proxy details before creating service
                    if not all([
                        account_dict.get('proxy_username'),
                        account_dict.get('proxy_password'),
                        account_dict.get('proxy_url'),
                        account_dict.get('proxy_port')
                    ]):
                        raise ValueError("Missing required proxy configuration")
                    
                    # Create service
                    oauth_service = OAuthSetupService(account_dict)
                    if not oauth_service:
                        raise RuntimeError("Failed to create OAuth service")

                    # Initialize browser and verify components
                    setup = await oauth_service.setup_browser_context()
                    if not setup or len(setup) != 3:
                        raise RuntimeError("Browser context setup failed")

                    playwright, browser, context = setup
                    if not all([playwright, browser, context]):
                        missing = []
                        if not playwright: missing.append('playwright')
                        if not browser: missing.append('browser')
                        if not context: missing.append('context')
                        raise RuntimeError(f"Missing browser components: {', '.join(missing)}")

                    # Test service with timeout
                    test_result = await asyncio.wait_for(
                        oauth_service.test_service(),
                        timeout=60.0  # 60 second timeout
                    )
                    if not test_result:
                        raise RuntimeError("Service initialization test failed")
                    
                    logger.info(f"Successfully validated service for account {account_no}")
                    break  # Success - exit retry loop
                    
                except asyncio.TimeoutError:
                    error_msg = f"Service test timed out on attempt {attempt + 1}"
                    logger.warning(error_msg)
                    
                    # Clean up resources if service was created
                    if oauth_service:
                        try:
                            await oauth_service.cleanup_resources()
                        except Exception as cleanup_error:
                            logger.error(f"Error during cleanup: {str(cleanup_error)}")
                        oauth_service = None
                    
                    if attempt == 2:  # Last attempt
                        raise HTTPException(
                            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                            detail="OAuth service initialization timed out after all retries"
                        )
                    await asyncio.sleep(5)  # Wait before retry
                    continue
                    
                except Exception as e:
                    error_msg = f"OAuth service initialization failed on attempt {attempt + 1}: {str(e)}"
                    logger.warning(error_msg)
                    
                    # Clean up resources if service was created
                    if oauth_service:
                        try:
                            await oauth_service.cleanup_resources()
                        except Exception as cleanup_error:
                            logger.error(f"Error during cleanup: {str(cleanup_error)}")
                        oauth_service = None
                    
                    if attempt == 2:  # Last attempt
                        # Update account status
                        account.validation_in_progress = ValidationState.FAILED
                        account.last_validation = error_msg
                        account.last_validation_time = datetime.utcnow()
                        await db.commit()
                        
                        # Broadcast failure
                        await broadcast_message(request, "oauth_status", {
                            "type": "oauth_status",
                            "account_no": account_no,
                            "status": "failed",
                            "error": error_msg,
                            "message": "OAuth setup failed: Service initialization failed",
                            "details": "Check oauth_setup.log for more information"
                        })
                        
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=error_msg
                        )
                    await asyncio.sleep(5)  # Wait before retry
                    continue
            
            # Get OAuth credentials with timeout and enhanced validation
            # Inside process_account function, replace the credentials handling section:

            # Get OAuth credentials with timeout and enhanced validation
            credentials = None
            try:
                # Get credentials with proper browser setup
                async with asyncio.timeout(600):  # 10 minute timeout
                    credentials = await oauth_service.get_developer_credentials()
                    
                    # Check for suspension response
                    if isinstance(credentials, dict) and credentials.get('error') == 'ACCOUNT_SUSPENDED':
                        logger.error(f"Account {account_no} is suspended")
                        try:
                            # Start a new transaction
                            await db.rollback()  # Rollback any existing transaction
                            
                            # Update account status
                            account.validation_in_progress = ValidationState.FAILED
                            account.last_validation = credentials['message']
                            account.last_validation_time = datetime.utcnow()
                            account.is_suspended = True
                            
                            if not await safe_commit(db):
                                logger.error(f"Failed to update suspension status for {account_no}")
                                raise HTTPException(
                                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                    detail="Failed to update suspension status"
                                )
                            
                            await broadcast_message(request, "oauth_status", {
                                "type": "oauth_status",
                                "account_no": account_no,
                                "status": "suspended",
                                "message": credentials['message']
                            })
                            
                            return {
                                "status": "suspended",
                                "account_no": account_no,
                                "message": credentials['message']
                            }
                            
                        except Exception as db_error:
                            logger.error(f"Database error handling suspension for {account_no}: {str(db_error)}")
                            await db.rollback()
                            raise HTTPException(
                                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail=f"Database error: {str(db_error)}"
                            )
                        
            except asyncio.TimeoutError:
                logger.error(f"OAuth setup timed out for account {account_no}")
                await db.rollback()  # Add rollback here
                account.validation_in_progress = ValidationState.FAILED
                account.last_validation = "OAuth setup timed out"
                account.last_validation_time = datetime.utcnow()
                if not await safe_commit(db):
                    logger.error("Failed to update timeout status")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to update timeout status"
                    )
                
                await broadcast_message(request, "oauth_status", {
                    "type": "oauth_status",
                    "account_no": account_no,
                    "status": "failed",
                    "message": "OAuth setup timed out after 10 minutes"
                })
                
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="OAuth setup timed out after 10 minutes"
                )
                
            except Exception as e:
                logger.error(f"Error getting OAuth credentials: {str(e)}")
                await db.rollback()  # Add rollback here
                account.validation_in_progress = ValidationState.FAILED
                account.last_validation = f"Error: {str(e)}"
                account.last_validation_time = datetime.utcnow()
                if not await safe_commit(db):
                    logger.error("Failed to update error status")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to update error status"
                    )
                
                await broadcast_message(request, "oauth_status", {
                    "type": "oauth_status",
                    "account_no": account_no,
                    "status": "failed",
                    "error": str(e),
                    "message": f"OAuth setup failed: {str(e)}"
                })
                
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(e)
                )

        # Process credentials
        if not credentials or (isinstance(credentials, dict) and credentials.get('error')):
            error_msg = "Failed to obtain OAuth credentials"
            if isinstance(credentials, dict):
                if credentials.get('error') == 'ACCOUNT_SUSPENDED':
                    error_msg = credentials.get('message', 'Account is suspended')
                else:
                    error_msg = credentials.get('message', error_msg)
            
            account.validation_in_progress = ValidationState.FAILED
            account.last_validation = error_msg
            account.last_validation_time = datetime.utcnow()
            if isinstance(credentials, dict) and credentials.get('error') == 'ACCOUNT_SUSPENDED':
                account.is_suspended = True
            if not await safe_commit(db):
                logger.error("Failed to update OAuth credentials")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to update OAuth credentials"
                )
            
            await broadcast_message(request, "oauth_status", {
                "type": "oauth_status",
                "account_no": account_no,
                "status": "failed" if not credentials.get('error') == 'ACCOUNT_SUSPENDED' else "suspended",
                "message": error_msg
            })
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_msg
            )

        # Update account with new credentials
        for key, value in credentials.items():
            setattr(account, key, value)
        account.validation_in_progress = ValidationState.COMPLETED
        account.last_validation = "OAuth setup completed successfully"
        account.last_validation_time = datetime.utcnow()
        await db.commit()
        
        # Broadcast completion
        await broadcast_message(request, "oauth_status", {
            "type": "oauth_status",
            "account_no": account_no,
            "status": "completed",
            "message": "OAuth credentials obtained successfully"
        })
        
        return {
            "status": "success",
            "account_no": account_no,
            "message": "OAuth setup completed successfully"
        }

    except Exception as e:
        logger.error(f"Error in OAuth setup for account {account_no}: {str(e)}", exc_info=True)
        try:
            if 'account' in locals():
                account.validation_in_progress = ValidationState.FAILED
                account.last_validation = f"Error: {str(e)}"
                if not await safe_commit(db):
                    logger.error("Failed to update final error status")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to update final error status"
                    )
                
                await broadcast_message(request, "oauth_status", {
                    "type": "oauth_status",
                    "account_no": account_no,
                    "status": "failed",
                    "error": str(e),
                    "message": f"OAuth setup failed: {str(e)}"
                })
        except Exception as inner_e:
            logger.error(f"Error updating failed status: {str(inner_e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.post("/password/update/bulk")
async def update_password(
    request: Request,
    threads: Optional[int] = Query(None)
):
    """Update password for multiple accounts in parallel using a worker queue"""
    try:
        # Get accounts and thread count from request body
        body = await request.json()
        account_numbers = body.get('accounts', [])
        
        # Use thread count from query param first, then body, then default
        num_threads = threads if threads is not None else body.get('threads', 6)
        
        # Validate thread count
        if not 1 <= num_threads <= 12:
            num_threads = 6  # Reset to default if invalid
        
        if not account_numbers:
            raise ValueError("No accounts provided")

        # Ensure all account numbers are strings
        account_numbers = [str(acc) for acc in account_numbers if acc]
        
        if not account_numbers:
            raise ValueError("No valid account numbers provided")

        logger.info(f"Processing password updates for accounts: {account_numbers} with {num_threads} threads")
        
        # Create semaphore for parallel processing
        semaphore = asyncio.Semaphore(num_threads)
        
        # Create queue and add accounts
        queue = asyncio.Queue()
        for acc_no in account_numbers:
            await queue.put(acc_no)
            
        # Track results
        successful = []
        failed = []
        results_lock = asyncio.Lock()
        
        # Worker function to process accounts
        async def worker(worker_id: int):
            while True:
                try:
                    # Try to get next account from queue with timeout
                    try:
                        acc_no = await asyncio.wait_for(queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        # No more accounts to process
                        break
                        
                    try:
                        # Process account with its own database session
                        async with get_task_db() as task_db:
                            result = await process_password_update(acc_no, task_db, semaphore, request)
                            
                        # Update results thread-safely
                        async with results_lock:
                            if isinstance(result, dict) and result.get('status') == 'success':
                                successful.append(acc_no)
                            else:
                                failed.append(acc_no)
                                logger.error(f"Failed to process account {acc_no}")
                                
                    except Exception as e:
                        logger.error(f"Error processing account {acc_no}: {str(e)}")
                        async with results_lock:
                            failed.append(acc_no)
                    finally:
                        queue.task_done()
                        
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Worker {worker_id} error: {str(e)}")
                    continue
        
        # Start limited number of workers
        workers = [
            asyncio.create_task(worker(i))
            for i in range(num_threads)
        ]
        
        # Wait for all accounts to be processed
        await queue.join()
        
        # Cancel and clean up workers
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        
        return {
            "status": "completed",
            "successful": successful,
            "failed": failed,
            "message": f"Updated passwords for {len(successful)} accounts successfully, {len(failed)} failed"
        }
        
    except ValueError as ve:
        logger.error(f"Validation error: {str(ve)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        logger.error(f"Error updating passwords: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


async def process_password_update(account_no: str, db: AsyncSession, semaphore: asyncio.Semaphore, request: Request):
    """Process password update for a single account"""
    try:
        logger.info(f"Starting password update for account {account_no}")
        
        # Get account from database
        result = await db.execute(
            select(Account).filter(Account.account_no == account_no)
        )
        account = result.scalar_one_or_none()
        
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found"
            )

        # Broadcast start
        await broadcast_message(request, "password_update", {
            "type": "password_update",
            "account_no": account_no,
            "status": "started",
            "message": "Starting password update..."
        })

        # Initialize password manager with minimal required fields
        account_dict = {
            'account_no': account.account_no,
            'login': account.login,
            'password': account.password,
            'auth_token': account.auth_token,
            'ct0': account.ct0,
            'two_fa': account.two_fa,
            'proxy_username': str(account.proxy_username),
            'proxy_password': str(account.proxy_password),
            'proxy_url': account.proxy_url,
            'proxy_port': str(account.proxy_port),
            'user_agent': account.user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        # Update password
        password_manager = PasswordManager(account_dict)
        result = await password_manager.update_password(semaphore)
        
        if result['success']:
            # Update account with new credentials
            account.password = result['new_credentials']['password']
            account.ct0 = result['new_credentials']['ct0']
            account.auth_token = result['new_credentials']['auth_token']
            account.last_validation = "Password updated successfully"
            account.last_validation_time = datetime.utcnow()
            await db.commit()
            
            # Broadcast completion
            await broadcast_message(request, "password_update", {
                "type": "password_update",
                "account_no": account_no,
                "status": "completed",
                "message": "Password updated successfully"
            })
            
            return {
                "status": "success",
                "account_no": account_no,
                "message": "Password updated successfully"
            }
        else:
            raise Exception(result['message'])

    except Exception as e:
        logger.error(f"Error updating password for account {account_no}: {str(e)}")
        await broadcast_message(request, "password_update", {
            "type": "password_update",
            "account_no": account_no,
            "status": "failed",
            "error": str(e),
            "message": f"Password update failed: {str(e)}"
        })
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.post("/download")
async def download_accounts(
    data: dict,
    db: AsyncSession = Depends(get_db)
):
    """Download selected accounts as CSV"""
    try:
        accounts = data.get('accounts', [])
        if not accounts:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No accounts selected"
            )
        
        result = await db.execute(
            select(Account).filter(Account.account_no.in_(accounts))
        )
        selected_accounts = result.scalars().all()
        
        # Convert to DataFrame with all fields including password and two_fa
        accounts_data = []
        for account in selected_accounts:
            account_dict = {
                col.name: getattr(account, col.name)
                for col in Account.__table__.columns
            }
            accounts_data.append(account_dict)
        
        df = pd.DataFrame(accounts_data)
        
        # Ensure password and two_fa columns are included
        required_columns = ['password', 'two_fa']
        for col in required_columns:
            if col not in df.columns:
                df[col] = None
        
        # Convert to CSV
        output = io.StringIO()
        df.to_csv(output, index=False)
        
        response = Response(
            content=output.getvalue(),
            media_type='text/csv',
            headers={
                'Content-Disposition': 'attachment; filename=accounts_export.csv'
            }
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Error downloading accounts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

async def parse_account_numbers(account_input: str) -> List[str]:
    """
    Parse account numbers from various input formats:
    - Single account number
    - Comma-separated list
    - JSON array of objects or strings
    
    Returns a list of validated account numbers
    """
    try:
        account_numbers = []
        
        # Handle empty input
        if not account_input:
            raise ValueError("No account data provided")
            
        # If input is already a list
        if isinstance(account_input, list):
            for item in account_input:
                if isinstance(item, dict):
                    acc_no = str(item.get('account_no', ''))
                else:
                    acc_no = str(item)
                if acc_no:
                    account_numbers.append(acc_no)
            return account_numbers
            
        # If input is a string
        if isinstance(account_input, str):
            # Try parsing as JSON
            if account_input.startswith('['):
                try:
                    data = json.loads(account_input)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                acc_no = str(item.get('account_no', ''))
                            else:
                                acc_no = str(item)
                            if acc_no:
                                account_numbers.append(acc_no)
                    return account_numbers
                except json.JSONDecodeError:
                    # If JSON parsing fails, try as comma-separated
                    pass
                    
            # Handle comma-separated input
            account_numbers = [
                num.strip() 
                for num in account_input.strip('[]').split(',') 
                if num.strip()
            ]
            
        # Validate and clean account numbers
        validated_numbers = []
        for acc_no in account_numbers:
            cleaned = str(acc_no).strip()
            if cleaned:
                validated_numbers.append(cleaned)
                
        if not validated_numbers:
            raise ValueError("No valid account numbers found in input")
            
        return validated_numbers
        
    except Exception as e:
        logger.error(f"Error parsing account numbers: {str(e)}")
        raise ValueError(f"Invalid account data provided: {str(e)}")

async def process_account_chunk(db: AsyncSession, accounts: List[dict]) -> tuple[int, List[str]]:
    """Process a chunk of accounts with proper error handling"""
    successful = 0
    errors = []
    
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
                
                # Set worker flag based on act_type
                if existing_account.act_type == 'worker':
                    existing_account.is_worker = True
                else:
                    existing_account.is_worker = False
                
                existing_account.is_active = True
                # Don't set validation status on import
                existing_account.validation_in_progress = ValidationState.PENDING
            else:
                # Create new account
                account_data['created_at'] = datetime.utcnow()
                
                # Set worker flag based on act_type from CSV
                account_data['is_worker'] = account_data.get('act_type') == 'worker'
                account_data['is_active'] = True
                account_data['validation_in_progress'] = ValidationState.PENDING
                
                db_account = Account(**account_data)
                db.add(db_account)
            
            successful += 1
            
        except Exception as e:
            errors.append(f"Error processing account {account_data.get('account_no', 'unknown')}: {str(e)}")
            continue
    
    try:
        await db.flush()
    except IntegrityError as e:
        logger.error(f"Database integrity error: {str(e)}")
        errors.append("Database integrity error: Possible duplicate account numbers")
        successful = 0  # Reset successful count for this chunk
    except Exception as e:
        logger.error(f"Database error: {str(e)}")
        errors.append(f"Database error: {str(e)}")
        successful = 0  # Reset successful count for this chunk
    
    return successful, errors

# Add logging for debugging
@router.get("/")
async def get_accounts(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100
):
    """Get all accounts"""
    try:
        query = select(Account).offset(skip).limit(limit)
        result = await db.execute(query)
        accounts = result.scalars().all()
        
        # Add debug logging
        logger.info(f"Retrieved {len(accounts)} accounts from database")
        for account in accounts:
            logger.debug(f"Account: {account.account_no}, Status: {account.oauth_setup_status}")
        
        return accounts
    except Exception as e:
        logger.error(f"Error fetching accounts: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching accounts: {str(e)}"
        )
