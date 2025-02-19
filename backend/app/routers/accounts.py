from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, BackgroundTasks, Query, Response, WebSocket, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc, asc
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
import csv
import io
from datetime import datetime, timedelta
import logging
import asyncio
from urllib.parse import quote, urlencode
import base64
import json
import pandas as pd

from ..database import get_db, db_manager
from ..models.account import Account, ValidationState
from ..schemas.account import (
    AccountResponse,
    AccountImportResponse,
    BulkValidationResponse,
    ValidationStatus,
    AccountBase,
    AccountCreate
)
from ..services.twitter_client import construct_proxy_url
from ..services.account_validator import validate_account as validate_account_service, validate_accounts_parallel
from ..services.account_recovery import recover_account
from ..services.captcha_solver import CaptchaSolver
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/activate-workers")
async def activate_worker_accounts(
    db: AsyncSession = Depends(get_db)
):
    """Activate and properly tag all worker accounts"""
    try:
        # Update all accounts that have auth_token and ct0
        result = await db.execute(
            select(Account).where(
                and_(
                    Account.auth_token.isnot(None),
                    Account.ct0.isnot(None),
                    Account.deleted_at.is_(None)
                )
            )
        )
        accounts = result.scalars().all()
        
        activated_count = 0
        for account in accounts:
            account.act_type = 'worker'
            account.is_worker = True
            account.is_active = True
            account.credentials_valid = True
            if account.validation_in_progress != ValidationState.VALIDATING:
                account.validation_in_progress = ValidationState.COMPLETED
            activated_count += 1
        
        await db.commit()
        
        return {
            "success": True,
            "message": f"Activated {activated_count} worker accounts",
            "activated_count": activated_count
        }
        
    except Exception as e:
        logger.error(f"Error activating worker accounts: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to activate worker accounts: {str(e)}"
        )

@router.get("/auth-url/{account_no}", description="Get authenticated Twitter URL for an account")
async def get_auth_url(
    account_no: str,
    db: AsyncSession = Depends(get_db)
):
    """Get authenticated Twitter URL for an account"""
    try:
        # Get account
        result = await db.execute(
            select(Account).where(
                and_(
                    Account.account_no == account_no,
                    Account.deleted_at.is_(None)
                )
            )
        )
        account = result.scalar_one_or_none()
        
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Account {account_no} not found"
            )

        # Check required fields
        required_fields = ['login', 'auth_token', 'ct0', 'proxy_username', 'proxy_password', 'proxy_url', 'proxy_port']
        missing_fields = [field for field in required_fields if not getattr(account, field)]
        if missing_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required fields: {', '.join(missing_fields)}"
            )

        # Construct proxy URL
        proxy_url = construct_proxy_url(
            username=account.proxy_username,
            password=account.proxy_password,
            host=account.proxy_url,
            port=account.proxy_port
        )

        # Create auth data object with full proxy details
        auth_data = {
            "auth_token": account.auth_token,
            "ct0": account.ct0,
            "user_agent": account.user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            "proxy_url": proxy_url,
            "proxy_username": account.proxy_username,
            "proxy_password": account.proxy_password
        }

        # Encode auth data
        auth_data_str = base64.b64encode(json.dumps(auth_data).encode()).decode()

        # Construct URL with auth data
        auth_url = f"/auth-twitter?data={quote(auth_data_str)}"

        return {
            "auth_url": auth_url,
            "username": account.login
        }

    except Exception as e:
        logger.error(f"Error generating auth URL for account {account_no}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# Internal function for cookie refresh that can be used by other services
async def refresh_cookies_internal(account_dict: dict) -> dict:
    """Internal function to refresh cookies for an account"""
    try:
        logger.info(f"Starting internal cookie refresh for account {account_dict.get('account_no')}")
        
        # Check required fields
        required_fields = ['login', 'password', 'proxy_username', 'proxy_password', 'proxy_url', 'proxy_port']
        missing_fields = [field for field in required_fields if not account_dict.get(field)]
        if missing_fields:
            error_msg = f"Missing required fields: {', '.join(missing_fields)}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg
            }
        
        # Setup proxy configuration
        proxy_config = {
            'server': f"http://{account_dict['proxy_url']}:{account_dict['proxy_port']}",
            'username': account_dict['proxy_username'],
            'password': account_dict['proxy_password']
        }
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                proxy=proxy_config
            )
            
            try:
                context = await browser.new_context(
                    user_agent=account_dict.get('user_agent') or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    viewport={'width': 1280, 'height': 800}
                )
                
                page = await context.new_page()
                
                # Navigate to login page with retries
                max_retries = 3
                retry_count = 0
                while retry_count < max_retries:
                    try:
                        logger.info(f"Navigating to Twitter login page (attempt {retry_count + 1}/{max_retries})...")
                        response = await page.goto('https://twitter.com/i/flow/login', timeout=60000)
                        break
                    except PlaywrightTimeoutError:
                        retry_count += 1
                        if retry_count == max_retries:
                            raise Exception("Could not connect to Twitter after multiple attempts")
                        logger.info(f"Retrying navigation... ({retry_count}/{max_retries})")
                        await asyncio.sleep(5)

                # Save initial state
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                await page.screenshot(path=f"internal_refresh_{timestamp}_initial.png")
                
                # Enter username with multiple selector attempts
                username_input = None
                for selector in ['input[autocomplete="username"]', 'input[name="text"]', 'input[type="text"]']:
                    try:
                        username_input = await page.wait_for_selector(selector, timeout=5000, state='visible')
                        if username_input:
                            break
                    except PlaywrightTimeoutError:
                        continue
                
                if not username_input:
                    raise Exception("Could not find username input field")
                
                await username_input.fill(account_dict['login'])
                await asyncio.sleep(2)
                await page.get_by_text("Next").click()
                await asyncio.sleep(2)

                # Check for captcha after username
                try:
                    arkose_frame = None
                    for frame in page.frames:
                        if 'arkoselabs' in frame.url:
                            arkose_frame = frame
                            logger.info("Found Arkose captcha frame after username")
                            break
                            
                    if arkose_frame:
                            logger.info("Attempting to solve captcha after username...")
                            # Pass through the exact field names from the database
                            solver_proxy_config = {
                                'proxy_url': account_dict['proxy_url'],
                                'proxy_port': account_dict['proxy_port'],
                                'proxy_username': account_dict['proxy_username'],
                                'proxy_password': account_dict['proxy_password']
                            }
                            captcha_solver = CaptchaSolver(solver_proxy_config)
                            await captcha_solver.setup_page_handlers(page)
                            if await captcha_solver.solve_captcha_challenge():
                                logger.info("Captcha solved successfully after username")
                            else:
                                logger.error("Failed to solve captcha after username")
                                raise Exception("Captcha solving failed after username")
                except Exception as e:
                    logger.error(f"Error handling captcha after username: {e}")
                    raise

                # Check for email verification input
                try:
                    email_input = await page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=5000)
                    if email_input:
                        logger.info("Found email verification input, filling with email...")
                        if account_dict.get('email'):
                            await email_input.fill(account_dict['email'])
                            await asyncio.sleep(2)
                            await page.get_by_text("Next").click()
                            await asyncio.sleep(2)
                        else:
                            logger.warning("Email verification required but no email available in account data")
                            raise Exception("Email verification required but no email available")
                except PlaywrightTimeoutError:
                    # No email verification needed, continue to password
                    pass
                
                # Check for captcha after email verification
                try:
                    arkose_frame = None
                    for frame in page.frames:
                        if 'arkoselabs' in frame.url:
                            arkose_frame = frame
                            logger.info("Found Arkose captcha frame after email verification")
                            break
                            
                        if arkose_frame:
                            logger.info("Attempting to solve captcha after email verification...")
                            # Pass through the exact field names from the database
                            solver_proxy_config = {
                                'proxy_url': account_dict['proxy_url'],
                                'proxy_port': account_dict['proxy_port'],
                                'proxy_username': account_dict['proxy_username'],
                                'proxy_password': account_dict['proxy_password']
                            }
                            captcha_solver = CaptchaSolver(solver_proxy_config)
                            await captcha_solver.setup_page_handlers(page)
                            if await captcha_solver.solve_captcha_challenge():
                                logger.info("Captcha solved successfully after email verification")
                            else:
                                logger.error("Failed to solve captcha after email verification")
                                raise Exception("Captcha solving failed after email verification")
                except Exception as e:
                    logger.error(f"Error handling captcha after email verification: {e}")
                    raise

                # Enter password with multiple selector attempts
                password_input = None
                for selector in ['input[name="password"]', 'input[type="password"]']:
                    try:
                        password_input = await page.wait_for_selector(selector, timeout=5000, state='visible')
                        if password_input:
                            break
                    except PlaywrightTimeoutError:
                        continue
                
                if not password_input:
                    raise Exception("Could not find password input field")
                
                await password_input.fill(account_dict['password'])
                await asyncio.sleep(2)

                # Check for captcha before clicking login
                try:
                    arkose_frame = None
                    for frame in page.frames:
                        if 'arkoselabs' in frame.url:
                            arkose_frame = frame
                            logger.info("Found Arkose captcha frame before login")
                            break
                            
                    if arkose_frame:
                        logger.info("Attempting to solve captcha before login...")
                        # Pass through the exact field names from the database
                        solver_proxy_config = {
                            'proxy_url': account_dict['proxy_url'],
                            'proxy_port': account_dict['proxy_port'],
                            'proxy_username': account_dict['proxy_username'],
                            'proxy_password': account_dict['proxy_password']
                        }
                        captcha_solver = CaptchaSolver(solver_proxy_config)
                        await captcha_solver.setup_page_handlers(page)
                        if await captcha_solver.solve_captcha_challenge():
                            logger.info("Captcha solved successfully before login")
                        else:
                            logger.error("Failed to solve captcha before login")
                            raise Exception("Captcha solving failed before login")
                except Exception as e:
                    logger.error(f"Error handling captcha before login: {e}")
                    raise
                
                # Try multiple ways to find login button
                try:
                    await page.get_by_text("Log in", exact=True).click()
                except Exception:
                    try:
                        await page.get_by_role("button", name="Log in").click()
                    except Exception:
                        await page.locator('[data-testid="LoginButton"]').click()
                
                await asyncio.sleep(3)

                # Check for captcha after login
                try:
                    arkose_frame = None
                    for frame in page.frames:
                        if 'arkoselabs' in frame.url:
                            arkose_frame = frame
                            logger.info("Found Arkose captcha frame after login")
                            break
                            
                        if arkose_frame:
                            logger.info("Attempting to solve captcha after login...")
                            # Pass through the exact field names from the database
                            solver_proxy_config = {
                                'proxy_url': account_dict['proxy_url'],
                                'proxy_port': account_dict['proxy_port'],
                                'proxy_username': account_dict['proxy_username'],
                                'proxy_password': account_dict['proxy_password']
                            }
                            captcha_solver = CaptchaSolver(solver_proxy_config)
                            await captcha_solver.setup_page_handlers(page)
                            if await captcha_solver.solve_captcha_challenge():
                                logger.info("Captcha solved successfully after login")
                            else:
                                logger.error("Failed to solve captcha after login")
                                raise Exception("Captcha solving failed after login")
                except Exception as e:
                    logger.error(f"Error handling captcha after login: {e}")
                    raise

                # Check if we still see password field after login attempt
                try:
                    password_input_after = await page.wait_for_selector('input[type="password"]', timeout=5000)
                    if password_input_after:
                        logger.info("Still seeing password input after login attempt, trying old password...")
                        if account_dict.get('old_password'):
                            await password_input_after.fill(account_dict['old_password'])
                            await asyncio.sleep(2)
                            await page.get_by_text("Log in").click()
                            await asyncio.sleep(3)
                            
                            # Handle 2FA for old password attempt if needed
                            try:
                                two_fa_input = await page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=5000)
                                if two_fa_input and account_dict.get('two_fa'):
                                    two_fa_page = await browser.new_page()
                                    try:
                                        await two_fa_page.goto(f'https://2fa.fb.rip/{account_dict["two_fa"]}', timeout=15000)
                                        await two_fa_page.wait_for_selector('#app', state='visible', timeout=10000)
                                        verify_code_element = await two_fa_page.wait_for_selector('#verifyCode', timeout=10000)
                                        if verify_code_element:
                                            code = await verify_code_element.text_content()
                                            digits = ''.join(c for c in code if c.isdigit())
                                            if digits and len(digits) == 6:
                                                await two_fa_input.fill(digits)
                                                await asyncio.sleep(2)
                                                
                                                # Click Next button after 2FA
                                                logger.info("Waiting for Next button...")
                                                next_button = await page.wait_for_selector('[data-testid="ocfEnterTextNextButton"]', 
                                                    state='visible',
                                                    timeout=10000
                                                )
                                                await asyncio.sleep(2)
                                                
                                                # Make sure button is in view
                                                await next_button.scroll_into_view_if_needed()
                                                await asyncio.sleep(1)
                                                
                                                # Try clicking with force first
                                                logger.info("Clicking Next button with force...")
                                                await next_button.click(force=True)
                                                await asyncio.sleep(2)
                                                
                                                # If force click didn't work, try JavaScript click
                                                logger.info("Clicking Next button with JavaScript...")
                                                await page.evaluate("""
                                                    const button = document.querySelector('[data-testid="ocfEnterTextNextButton"]');
                                                    if (button) {
                                                        button.click();
                                                        button.dispatchEvent(new MouseEvent('click', {
                                                            bubbles: true,
                                                            cancelable: true,
                                                            view: window
                                                        }));
                                                    }
                                                """)
                                                await asyncio.sleep(5)  # Longer wait after click
                                                
                                                # Wait for home page
                                                try:
                                                    await page.wait_for_url("https://twitter.com/home", timeout=15000)
                                                    logger.info("Successfully reached twitter.com home page")
                                                except PlaywrightTimeoutError:
                                                    try:
                                                        await page.wait_for_url("https://x.com/home", timeout=15000)
                                                        logger.info("Successfully reached x.com home page")
                                                    except PlaywrightTimeoutError:
                                                        raise Exception("Failed to reach home page after clicking Next button")
                                    finally:
                                        await two_fa_page.close()
                            except PlaywrightTimeoutError:
                                pass

                            # Check if old password login succeeded
                            try:
                                await page.wait_for_url("https://twitter.com/home", timeout=15000)
                                logger.info("Login successful with old password")
                                # Return success with cookies and old password
                                cookies = await context.cookies()
                                ct0 = next((c['value'] for c in cookies if c['name'] == 'ct0'), None)
                                auth_token = next((c['value'] for c in cookies if c['name'] == 'auth_token'), None)
                                if not ct0 or not auth_token:
                                    raise Exception("Failed to extract required cookies")
                                return {
                                    "success": True,
                                    "ct0": ct0,
                                    "auth_token": auth_token,
                                    "password": account_dict['old_password']  # Return old password to update DB
                                }
                            except PlaywrightTimeoutError:
                                try:
                                    await page.wait_for_url("https://x.com/home", timeout=15000)
                                    logger.info("Login successful with old password on x.com")
                                    # Return success with cookies
                                    cookies = await context.cookies()
                                    ct0 = next((c['value'] for c in cookies if c['name'] == 'ct0'), None)
                                    auth_token = next((c['value'] for c in cookies if c['name'] == 'auth_token'), None)
                                    if not ct0 or not auth_token:
                                        raise Exception("Failed to extract required cookies")
                                    return {
                                        "success": True,
                                        "ct0": ct0,
                                        "auth_token": auth_token,
                                        "password": account_dict['old_password']  # Return old password so caller can update DB
                                    }
                                except PlaywrightTimeoutError:
                                    raise Exception("Login failed with both new and old passwords")
                except PlaywrightTimeoutError:
                    # No password field found after login, continue normal flow
                    pass
                
                # Enhanced 2FA handling
                try:
                    two_fa_input = await page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=5000)
                    if two_fa_input:
                        if account_dict.get('two_fa'):
                            # Get 2FA code first
                            two_fa_page = await browser.new_page()
                            digits = None
                            try:
                                await two_fa_page.goto(f'https://2fa.fb.rip/{account_dict["two_fa"]}', timeout=15000)
                                await two_fa_page.wait_for_selector('#app', state='visible', timeout=10000)
                                verify_code_element = await two_fa_page.wait_for_selector('#verifyCode', timeout=10000)
                                if verify_code_element:
                                    code = await verify_code_element.text_content()
                                    digits = ''.join(c for c in code if c.isdigit())
                                    if not digits or len(digits) != 6:
                                        raise Exception("Invalid 2FA code format from service")
                                else:
                                    raise Exception("Could not find 2FA code element")
                            except PlaywrightTimeoutError:
                                raise Exception("Timeout connecting to 2FA service")
                            finally:
                                await two_fa_page.close()

                            if digits:
                                # Enter 2FA code
                                await two_fa_input.fill(digits)
                                await asyncio.sleep(2)
                                
                                # Click Next button after 2FA
                                try:
                                    logger.info("Waiting for Next button...")
                                    next_button = await page.wait_for_selector('[data-testid="ocfEnterTextNextButton"]', 
                                        state='visible',
                                        timeout=10000
                                    )
                                    await asyncio.sleep(2)
                                    
                                    # Make sure button is in view
                                    await next_button.scroll_into_view_if_needed()
                                    await asyncio.sleep(1)
                                    
                                    # Try clicking with force first
                                    logger.info("Clicking Next button with force...")
                                    await next_button.click(force=True)
                                    await asyncio.sleep(2)
                                    
                                    # If force click didn't work, try JavaScript click
                                    logger.info("Clicking Next button with JavaScript...")
                                    await page.evaluate("""
                                        const button = document.querySelector('[data-testid="ocfEnterTextNextButton"]');
                                        if (button) {
                                            button.click();
                                            button.dispatchEvent(new MouseEvent('click', {
                                                bubbles: true,
                                                cancelable: true,
                                                view: window
                                            }));
                                        }
                                    """)
                                    await asyncio.sleep(5)  # Longer wait after click
                                    
                                    # Wait for home page
                                    try:
                                        await page.wait_for_url("https://twitter.com/home", timeout=15000)
                                        logger.info("Successfully reached twitter.com home page")
                                    except PlaywrightTimeoutError:
                                        try:
                                            await page.wait_for_url("https://x.com/home", timeout=15000)
                                            logger.info("Successfully reached x.com home page")
                                        except PlaywrightTimeoutError:
                                            raise Exception("Failed to reach home page after clicking Next button")
                                        
                                except Exception as e:
                                    logger.error(f"Error clicking Next button after 2FA: {str(e)}")
                                    raise Exception(f"Failed to click Next button after 2FA: {str(e)}")
                        else:
                            logger.warning(f"2FA required for account {account_dict.get('account_no')} but no 2FA code available")
                            raise Exception("2FA required but no 2FA code available")
                except PlaywrightTimeoutError:
                    # No 2FA prompt found, continue
                    pass
                
                # Enhanced error checking
                try:
                    error_selectors = [
                        '[data-testid="error-detail"]',
                        '.alert-message',
                        '.error-text',
                        '[role="alert"]'
                    ]
                    
                    for selector in error_selectors:
                        try:
                            error_element = await page.wait_for_selector(selector, timeout=2000)
                            if error_element:
                                error_text = await error_element.text_content()
                                if error_text:
                                    raise Exception(f"Login failed: {error_text}")
                        except PlaywrightTimeoutError:
                            continue
                except PlaywrightTimeoutError:
                    pass
                
                # Verify login success
                try:
                    await page.wait_for_url("https://twitter.com/home", timeout=15000)
                except PlaywrightTimeoutError:
                    try:
                        await page.wait_for_url("https://x.com/home", timeout=15000)
                    except PlaywrightTimeoutError:
                        raise Exception("Login verification failed")
                
                # Extract cookies
                cookies = await context.cookies()
                ct0 = next((c['value'] for c in cookies if c['name'] == 'ct0'), None)
                auth_token = next((c['value'] for c in cookies if c['name'] == 'auth_token'), None)
                
                if not ct0 or not auth_token:
                    raise Exception("Failed to extract required cookies")
                
                return {
                    "success": True,
                    "ct0": ct0,
                    "auth_token": auth_token
                }
                
            finally:
                await browser.close()
                
    except Exception as e:
        logger.error(f"Error in internal cookie refresh: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

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

@router.get("", response_model=List[AccountResponse])
async def get_accounts(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: Optional[int] = Query(None, ge=1),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = Query('asc', regex='^(asc|desc)$')
):
    try:
        logger.info(f"GET /accounts/ called with skip={skip}, limit={limit}, search={search}")
        
        # Verify database connection
        if not db_manager.is_connected:
            logger.error("Database connection not available")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database connection not available"
            )
            
        # Build base query
        stmt = select(Account).where(Account.deleted_at.is_(None))
        
        if search:
            stmt = stmt.where(
                or_(
                    Account.account_no.ilike(f"%{search}%"),
                    Account.login.ilike(f"%{search}%"),
                    Account.email.ilike(f"%{search}%")
                )
            )
        
        # Get total count before pagination
        count_query = select(func.count()).select_from(stmt)
        total_count = await db.scalar(count_query)

        # Add ordering based on sort parameters
        if sort_by:
            column = getattr(Account, sort_by, None)
            if column is not None:
                stmt = stmt.order_by(column.desc() if sort_order == 'desc' else column.asc())
            else:
                stmt = stmt.order_by(Account.created_at.desc())
        
        # Add pagination
        stmt = stmt.offset(skip).limit(limit)
        
        # Execute query with explicit refresh
        result = await db.execute(stmt)
        accounts = result.scalars().all()
        
        # Log results
        logger.info(f"Found {len(accounts)} accounts")
        
        # Convert accounts to response model
        response_accounts = []
        for account in accounts:
            try:
                # Check if account is being processed
                if account.validation_in_progress == ValidationState.VALIDATING:
                    oauth_status = 'IN_PROGRESS'
                else:
                    # Check if all OAuth credentials exist and are non-empty
                    has_oauth = all(
                        getattr(account, field) and str(getattr(account, field)).strip()
                        for field in [
                            'consumer_key', 'consumer_secret', 'bearer_token',
                            'access_token', 'access_token_secret', 'client_id', 'client_secret'
                        ]
                    )
                    oauth_status = 'COMPLETED' if has_oauth else 'PENDING'

                response_account = {
                    'id': account.id,
                    'account_no': account.account_no,
                    'login': account.login,
                    'email': account.email,
                    'act_type': account.act_type,
                    'is_active': account.is_active,
                    'is_worker': account.is_worker,
                    'created_at': account.created_at.isoformat() if account.created_at else None,
                    'updated_at': account.updated_at.isoformat() if account.updated_at else None,
                    'validation_in_progress': account.validation_in_progress.value if account.validation_in_progress else None,
                    'last_validation': account.last_validation,
                    'last_validation_time': account.last_validation_time.isoformat() if account.last_validation_time else None,
                    # OAuth credentials
                    'consumer_key': account.consumer_key or '',
                    'consumer_secret': account.consumer_secret or '',
                    'bearer_token': account.bearer_token or '',
                    'access_token': account.access_token or '',
                    'access_token_secret': account.access_token_secret or '',
                    'client_id': account.client_id or '',
                    'client_secret': account.client_secret or '',
                    # OAuth status
                    'oauth_setup_status': oauth_status,
                    'password_status': 'COMPLETED' if account.password and len(account.password) > 20 else 'NEEDS SETUP'
                }
                response_accounts.append(response_account)
            except Exception as e:
                logger.error(f"Error converting account {account.account_no} to response model: {e}")
                continue
        
        # Return as JSON response with total count
        return JSONResponse(content={
            "accounts": response_accounts,
            "total": total_count
        })
        
    except Exception as e:
        logger.error(f"Error fetching accounts: {str(e)}")
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

        # Convert account to dict with all required fields
        account_dict = {
            'account_no': account.account_no,
            'login': account.login,
            'email': account.email,
            'email_password': account.email_password,
            'password': account.password,
            'old_password': account.old_password,
            'auth_token': account.auth_token,
            'ct0': account.ct0,
            'user_agent': account.user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'proxy_username': account.proxy_username,
            'proxy_password': account.proxy_password,
            'proxy_url': account.proxy_url,
            'proxy_port': str(account.proxy_port),
            'two_fa': account.two_fa  # Add two_fa field
        }

        # Perform validation
        logger.info(f"Calling validate_account_service for {account_no}")
        validation_result = await validate_account_service(account_dict)
        logger.info(f"Validation result for {account_no}: {validation_result}")

        # Update account status
        account.last_validation = validation_result
        account.last_validation_time = datetime.utcnow()
        account.validation_in_progress = ValidationState.COMPLETED
        account.is_active = True
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
            select(Account).where(Account.deleted_at.is_(None))
        )
        accounts = result.scalars().all()

        if not accounts:
            return {
                "status": "success",
                "message": "No accounts to validate",
                "total": 0
            }

        # Calculate batch information
        total_accounts = len(accounts)
        batch_size = threads  # Use thread count as batch size
        total_batches = (total_accounts + batch_size - 1) // batch_size
        
        # Convert accounts to list of dicts with batch info
        account_dicts = []
        for i, account in enumerate(accounts):
            batch_index = i // batch_size
            account_dict = {
                'account_no': account.account_no,
                'login': account.login,
                'email': account.email,
                'email_password': account.email_password,
                'password': account.password,
                'old_password': account.old_password,
                'auth_token': account.auth_token,
                'ct0': account.ct0,
                'user_agent': account.user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'proxy_username': account.proxy_username,
                'proxy_password': account.proxy_password,
                'proxy_url': account.proxy_url,
                'proxy_port': str(account.proxy_port),
                'two_fa': account.two_fa,
                'batch_index': batch_index,
                'total_batches': total_batches
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
                
                # Create broadcast function for real-time updates
                async def broadcast_update(update_data: dict):
                    await broadcast_message(request, "task_update", {
                        "task_type": "validation",
                        **update_data
                    })

                # Pass broadcast function to parallel validation
                results = await validate_accounts_parallel(account_dicts, threads, broadcast_update)
                
                # Update accounts with results
                for result in results:
                    try:
                        account = next(acc for acc in accounts if acc.account_no == result['account_no'])
                        account.last_validation = result['status']
                        account.last_validation_time = datetime.utcnow()
                        account.validation_in_progress = ValidationState.COMPLETED
                        
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

        # Prepare account dict with all required fields
        account_dict = {
            'account_no': account.account_no,
            'login': account.login,
            'email': account.email,
            'email_password': account.email_password,
            'password': account.password,
            'old_password': account.old_password,
            'auth_token': account.auth_token,
            'ct0': account.ct0,
            'user_agent': account.user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'proxy_username': account.proxy_username,
            'proxy_password': account.proxy_password,
            'proxy_url': account.proxy_url,
            'proxy_port': str(account.proxy_port),
            'two_fa': account.two_fa  # Add two_fa field
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

@router.post("/refresh-cookies/{account_no}")
async def refresh_cookies(
    account_no: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Refresh cookies for an account using Playwright"""
    try:
        logger.info(f"Starting cookie refresh for account {account_no}")
        
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

        # Check required fields
        required_fields = ['login', 'password', 'proxy_username', 'proxy_password', 'proxy_url', 'proxy_port']
        missing_fields = [field for field in required_fields if not getattr(account, field)]
        if missing_fields:
            error_msg = f"Missing required fields: {', '.join(missing_fields)}"
            logger.error(error_msg)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )

        # Broadcast start status
        await broadcast_message(request, "task_update", {
            "task_type": "cookie_refresh",
            "account_no": account_no,
            "status": "started",
            "message": "Starting cookie refresh..."
        })
        
        # Setup proxy configuration
        proxy_config = {
            'server': f"http://{account.proxy_url}:{account.proxy_port}",
            'username': account.proxy_username,
            'password': account.proxy_password
        }
        
        async with async_playwright() as p:
            # Launch browser with proxy in headful mode for debugging
            browser = await p.chromium.launch(
                headless=True,
                proxy=proxy_config
            )
            
            try:
                # Create new context
                context = await browser.new_context(
                    user_agent=account.user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    viewport={'width': 1280, 'height': 800}
                )
                
                page = await context.new_page()
                
                # Navigate to login page with retries and enhanced error handling
                max_retries = 3
                retry_count = 0
                while retry_count < max_retries:
                    try:
                        logger.info(f"Navigating to Twitter login page (attempt {retry_count + 1}/{max_retries})...")
                        response = await page.goto('https://twitter.com/i/flow/login', timeout=60000)
                        break
                    except PlaywrightTimeoutError:
                        retry_count += 1
                        if retry_count == max_retries:
                            raise Exception("Could not connect to Twitter after multiple attempts. Please check your internet connection or proxy settings.")
                        logger.info(f"Retrying navigation... ({retry_count}/{max_retries})")
                        await asyncio.sleep(5)  # Wait before retry
                
                try:
                    if not response:
                        raise Exception("No response received from Twitter")
                    if not response.ok:
                        raise Exception(f"HTTP {response.status}: {response.status_text}")
                    
                    # Check if page loaded correctly with timeout
                    try:
                        await page.wait_for_load_state('networkidle', timeout=30000)
                    except PlaywrightTimeoutError:
                        logger.warning("Network did not reach idle state, proceeding anyway...")
                        # Take screenshot of current state
                        await page.screenshot(path="network_not_idle.png")
                    
                    # Save initial page state with timestamp
                    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                    await page.screenshot(path=f"initial_page_{timestamp}.png")
                    html_content = await page.content()
                    with open(f"initial_page_{timestamp}.html", "w", encoding="utf-8") as f:
                        f.write(html_content)
                        
                    # Log page title for debugging
                    title = await page.title()
                    logger.info(f"Page title: {title}")
                    
                except PlaywrightTimeoutError:
                    raise Exception("Could not connect to Twitter. Please check your internet connection or proxy settings.")
                except Exception as e:
                    raise Exception(f"Error loading Twitter login page: {str(e)}")
                
                # Take screenshot before entering username
                await page.screenshot(path=f"debug_screenshot_0.png")
                
                # Enter username
                try:
                    # Wait for username field with multiple selector attempts
                    logger.info("Waiting for username input field...")
                    selectors = [
                        'input[autocomplete="username"]',
                        'input[name="text"]',
                        'input[data-testid="text-input-username"]',
                        'input[type="text"]'
                    ]
                    username_input = None
                    for selector in selectors:
                        try:
                            logger.info(f"Trying selector: {selector}")
                            username_input = await page.wait_for_selector(selector, timeout=5000, state='visible')
                            if username_input:
                                logger.info(f"Found username input with selector: {selector}")
                                break
                        except PlaywrightTimeoutError:
                            continue
                    if not username_input:
                        # Save page content for debugging
                        html_content = await page.content()
                        with open("login_page_debug.html", "w", encoding="utf-8") as f:
                            f.write(html_content)
                        raise Exception("Could not find username input field")
                    
                    logger.info("Found username input, filling...")
                    await username_input.fill(account.login)
                    await asyncio.sleep(2)
                    
                    # Take screenshot after entering username
                    await page.screenshot(path=f"debug_screenshot_1.png")
                    
                    logger.info("Clicking Next button...")
                    next_button = await page.get_by_text("Next").click()
                    await asyncio.sleep(2)

                    # Check for captcha after username
                    try:
                        arkose_frame = None
                        for frame in page.frames:
                            if 'arkoselabs' in frame.url:
                                arkose_frame = frame
                                logger.info("Found Arkose captcha frame after username")
                                break
                                
                        if arkose_frame:
                            logger.info("Attempting to solve captcha after username...")
                            # Pass through the exact field names from the database
                            solver_proxy_config = {
                                'proxy_url': account_dict['proxy_url'],
                                'proxy_port': account_dict['proxy_port'],
                                'proxy_username': account_dict['proxy_username'],
                                'proxy_password': account_dict['proxy_password']
                            }
                            captcha_solver = CaptchaSolver(solver_proxy_config)
                            await captcha_solver.setup_page_handlers(page)
                            if await captcha_solver.solve_captcha_challenge():
                                logger.info("Captcha solved successfully after username")
                            else:
                                logger.error("Failed to solve captcha after username")
                                raise Exception("Captcha solving failed after username")
                    except Exception as e:
                        logger.error(f"Error handling captcha after username: {e}")
                        raise

                    # Check for email verification input
                    try:
                        email_input = await page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=5000)
                        if email_input:
                            logger.info("Found email verification input, filling with email...")
                            if account.email:
                                await email_input.fill(account.email)
                                await asyncio.sleep(2)
                                await page.get_by_text("Next").click()
                                await asyncio.sleep(2)
                            else:
                                logger.warning("Email verification required but no email available in account data")
                                raise Exception("Email verification required but no email available")
                    except PlaywrightTimeoutError:
                        # No email verification needed, continue to password
                        pass
                    
                except PlaywrightTimeoutError as e:
                    # Save page content and screenshot for debugging
                    await page.screenshot(path="login_error.png")
                    html_content = await page.content()
                    with open("login_error.html", "w", encoding="utf-8") as f:
                        f.write(html_content)
                    raise Exception(f"Could not find login form elements. Error: {str(e)}")
                
                    # Check for captcha after email verification
                    try:
                        arkose_frame = None
                        for frame in page.frames:
                            if 'arkoselabs' in frame.url:
                                arkose_frame = frame
                                logger.info("Found Arkose captcha frame after email verification")
                                break
                                
                        if arkose_frame:
                            logger.info("Attempting to solve captcha after email verification...")
                            # Pass through the exact field names from the database
                            solver_proxy_config = {
                                'proxy_url': account_dict['proxy_url'],
                                'proxy_port': account_dict['proxy_port'],
                                'proxy_username': account_dict['proxy_username'],
                                'proxy_password': account_dict['proxy_password']
                            }
                            captcha_solver = CaptchaSolver(solver_proxy_config)
                            await captcha_solver.setup_page_handlers(page)
                            if await captcha_solver.solve_captcha_challenge():
                                logger.info("Captcha solved successfully after email verification")
                            else:
                                logger.error("Failed to solve captcha after email verification")
                                raise Exception("Captcha solving failed after email verification")
                    except Exception as e:
                        logger.error(f"Error handling captcha after email verification: {e}")
                        raise

                    # Enter password with enhanced error handling
                if not account.password:
                    raise Exception("Password is required but not available")

                try:
                    logger.info("Waiting for password input field...")
                    # Take screenshot before password entry
                    await page.screenshot(path=f"debug_screenshot_2.png")
                    
                    # Try multiple selectors for password field
                    password_selectors = [
                        'input[name="password"]',
                        'input[type="password"]',
                        'input[data-testid="password-input"]'
                    ]
                    password_input = None
                    for selector in password_selectors:
                        try:
                            logger.info(f"Trying password selector: {selector}")
                            password_input = await page.wait_for_selector(selector, timeout=5000, state='visible')
                            if password_input:
                                logger.info(f"Found password input with selector: {selector}")
                                break
                        except PlaywrightTimeoutError:
                            continue
                    if not password_input:
                        # Save page content for debugging
                        html_content = await page.content()
                        with open("password_page_debug.html", "w", encoding="utf-8") as f:
                            f.write(html_content)
                        raise Exception("Could not find password input field")
                    
                    logger.info("Found password input, filling...")
                    await password_input.fill(account.password)
                    await asyncio.sleep(2)

                    # Check for captcha before clicking login
                    try:
                        arkose_frame = None
                        for frame in page.frames:
                            if 'arkoselabs' in frame.url:
                                arkose_frame = frame
                                logger.info("Found Arkose captcha frame before login")
                                break
                                
                        if arkose_frame:
                            logger.info("Attempting to solve captcha before login...")
                            # Pass through the exact field names from the database
                            solver_proxy_config = {
                                'proxy_url': account_dict['proxy_url'],
                                'proxy_port': account_dict['proxy_port'],
                                'proxy_username': account_dict['proxy_username'],
                                'proxy_password': account_dict['proxy_password']
                            }
                            captcha_solver = CaptchaSolver(solver_proxy_config)
                            await captcha_solver.setup_page_handlers(page)
                            if await captcha_solver.solve_captcha_challenge():
                                logger.info("Captcha solved successfully before login")
                            else:
                                logger.error("Failed to solve captcha before login")
                                raise Exception("Captcha solving failed before login")
                    except Exception as e:
                        logger.error(f"Error handling captcha before login: {e}")
                        raise
                    
                    # Take screenshot after entering password
                    await page.screenshot(path=f"debug_screenshot_3.png")
                    
                    logger.info("Clicking Log in button...")
                    # Try multiple ways to find login button
                    login_button = None
                    try:
                        # Try by text content
                        login_button = await page.get_by_text("Log in", exact=True).click()
                    except Exception:
                        try:
                            # Try by role
                            login_button = await page.get_by_role("button", name="Log in").click()
                        except Exception:
                            try:
                                # Try by test ID
                                login_button = await page.locator('[data-testid="LoginButton"]').click()
                            except Exception:
                                raise Exception("Could not find Log in button using any method")
                    await asyncio.sleep(3)

                    # Check for captcha after login
                    try:
                        arkose_frame = None
                        for frame in page.frames:
                            if 'arkoselabs' in frame.url:
                                arkose_frame = frame
                                logger.info("Found Arkose captcha frame after login")
                                break
                                
                        if arkose_frame:
                            logger.info("Attempting to solve captcha after login...")
                            # Pass through the exact field names from the database
                            solver_proxy_config = {
                                'proxy_url': account_dict['proxy_url'],
                                'proxy_port': account_dict['proxy_port'],
                                'proxy_username': account_dict['proxy_username'],
                                'proxy_password': account_dict['proxy_password']
                            }
                            captcha_solver = CaptchaSolver(solver_proxy_config)
                            await captcha_solver.setup_page_handlers(page)
                            if await captcha_solver.solve_captcha_challenge():
                                logger.info("Captcha solved successfully after login")
                            else:
                                logger.error("Failed to solve captcha after login")
                                raise Exception("Captcha solving failed after login")
                    except Exception as e:
                        logger.error(f"Error handling captcha after login: {e}")
                        raise

                    # Check if we still see password field after login attempt
                    try:
                        password_input_after = await page.wait_for_selector('input[type="password"]', timeout=5000)
                        if password_input_after:
                            logger.info("Still seeing password input after login attempt, trying old password...")
                            if account.old_password:
                                # Try old password
                                await password_input_after.fill(account.old_password)
                                await asyncio.sleep(2)
                                await page.get_by_text("Log in").click()
                                await asyncio.sleep(3)
                                
                                # Handle 2FA for old password attempt if needed
                                try:
                                    two_fa_input = await page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=5000)
                                    if two_fa_input and account.two_fa:
                                        two_fa_page = await browser.new_page()
                                        try:
                                            await two_fa_page.goto(f'https://2fa.fb.rip/{account.two_fa}', timeout=15000)
                                            await two_fa_page.wait_for_selector('#app', state='visible', timeout=10000)
                                            verify_code_element = await two_fa_page.wait_for_selector('#verifyCode', timeout=10000)
                                            if verify_code_element:
                                                code = await verify_code_element.text_content()
                                                digits = ''.join(c for c in code if c.isdigit())
                                                if digits and len(digits) == 6:
                                                    await two_fa_input.fill(digits)
                                                    await asyncio.sleep(2)
                                                    
                                                    # Try simple text-based click first (same as other steps)
                                                    try:
                                                        await page.get_by_text("Next").click()
                                                    except Exception:
                                                        # Fallback to CSS class if needed
                                                        await page.click('div[class*="css-146c3p1"][class*="r-bcqeeo"]')
                                                    
                                                    await asyncio.sleep(3)
                                        finally:
                                            await two_fa_page.close()
                                except PlaywrightTimeoutError:
                                    pass

                                # Check if old password login succeeded
                                try:
                                    await page.wait_for_url("https://twitter.com/home", timeout=15000)
                                    # If we get here, old password worked
                                    # Swap passwords in database
                                    temp_password = account.password
                                    account.password = account.old_password
                                    account.old_password = temp_password
                                    await db.commit()
                                    logger.info("Login successful with old password, passwords swapped")
                                    
                                    # Extract cookies since login was successful
                                    cookies = await context.cookies()
                                    ct0 = next((c['value'] for c in cookies if c['name'] == 'ct0'), None)
                                    auth_token = next((c['value'] for c in cookies if c['name'] == 'auth_token'), None)
                                    if not ct0 or not auth_token:
                                        raise Exception("Failed to extract required cookies")
                                    
                                    # Update account with new cookies
                                    account.ct0 = ct0
                                    account.auth_token = auth_token
                                    account.status = 'active'
                                    account.last_validation = 'Cookies refreshed successfully with old password'
                                    account.last_validation_time = datetime.utcnow()
                                    await db.commit()
                                    
                                    return {
                                        "success": True,
                                        "message": "Cookies refreshed successfully with old password",
                                        "ct0": ct0,
                                        "auth_token": auth_token
                                    }
                                except PlaywrightTimeoutError:
                                    try:
                                        await page.wait_for_url("https://x.com/home", timeout=15000)
                                        # If we get here, old password worked on x.com
                                        temp_password = account.password
                                        account.password = account.old_password
                                        account.old_password = temp_password
                                        await db.commit()
                                        logger.info("Login successful with old password on x.com, passwords swapped")
                                        
                                        # Extract cookies since login was successful
                                        cookies = await context.cookies()
                                        ct0 = next((c['value'] for c in cookies if c['name'] == 'ct0'), None)
                                        auth_token = next((c['value'] for c in cookies if c['name'] == 'auth_token'), None)
                                        if not ct0 or not auth_token:
                                            raise Exception("Failed to extract required cookies")
                                        
                                        # Update account with new cookies
                                        account.ct0 = ct0
                                        account.auth_token = auth_token
                                        account.status = 'active'
                                        account.last_validation = 'Cookies refreshed successfully with old password'
                                        account.last_validation_time = datetime.utcnow()
                                        await db.commit()
                                        
                                        return {
                                            "success": True,
                                            "message": "Cookies refreshed successfully with old password",
                                            "ct0": ct0,
                                            "auth_token": auth_token
                                        }
                                    except PlaywrightTimeoutError:
                                        raise Exception("Login failed with both new and old passwords")
                    except PlaywrightTimeoutError:
                        # No password field found after login, continue normal flow
                        pass
                    
                except PlaywrightTimeoutError as e:
                    # Save page content and screenshot for debugging
                    await page.screenshot(path="password_error.png")
                    html_content = await page.content()
                    with open("password_error.html", "w", encoding="utf-8") as f:
                        f.write(html_content)
                    raise Exception(f"Could not find password form elements. Error: {str(e)}")
                
                # Handle 2FA if needed
                try:
                    two_fa_input = await page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=5000)
                    if two_fa_input:
                        if account.two_fa:
                            # Get 2FA code first
                            two_fa_page = await browser.new_page()
                            digits = None
                            try:
                                await two_fa_page.goto(f'https://2fa.fb.rip/{account.two_fa}', timeout=15000)
                                await two_fa_page.wait_for_selector('#app', state='visible', timeout=10000)
                                verify_code_element = await two_fa_page.wait_for_selector('#verifyCode', timeout=10000)
                                if verify_code_element:
                                    code = await verify_code_element.text_content()
                                    digits = ''.join(c for c in code if c.isdigit())
                                    if not digits or len(digits) != 6:
                                        raise Exception("Invalid 2FA code format from service")
                                else:
                                    raise Exception("Could not find 2FA code element")
                            except PlaywrightTimeoutError:
                                raise Exception("Timeout connecting to 2FA service")
                            finally:
                                await two_fa_page.close()

                            if digits:
                                # Enter 2FA code
                                await two_fa_input.fill(digits)
                                await asyncio.sleep(2)
                                
                                # Click Next button (same approach as other steps)
                                await page.get_by_text("Next").click()
                                
                                # Wait longer for navigation after 2FA
                                await asyncio.sleep(5)
                                
                                # Wait for home page
                                try:
                                    await page.wait_for_url("https://x.com/home", timeout=15000)
                                    logger.info("Successfully reached home page after 2FA")
                                except PlaywrightTimeoutError:
                                    raise Exception("Failed to reach home page after 2FA")
                        else:
                            logger.warning(f"2FA required for account {account_no} but no 2FA code available")
                            raise Exception("2FA required but no 2FA code available")
                except PlaywrightTimeoutError:
                    # No 2FA prompt found, continue
                    pass
                
                # Enhanced error message checking
                try:
                    # Take screenshot before error check
                    await page.screenshot(path="before_error_check.png")
                    
                    # Check multiple error selectors
                    error_selectors = [
                        '[data-testid="error-detail"]',
                        '.alert-message',
                        '.error-text',
                        '[role="alert"]'
                    ]
                    
                    for selector in error_selectors:
                        try:
                            error_element = await page.wait_for_selector(selector, timeout=2000)
                            if error_element:
                                error_text = await error_element.text_content()
                                if error_text:
                                    # Save page state for debugging
                                    await page.screenshot(path="error_state.png")
                                    html_content = await page.content()
                                    with open("error_page.html", "w", encoding="utf-8") as f:
                                        f.write(html_content)
                                    
                                    # Try new password up to 3 times
                                    retry_count = 1
                                    max_retries = 3
                                    
                                    while retry_count < max_retries:
                                        logger.info(f"Retrying with new password (attempt {retry_count + 1}/{max_retries})...")
                                        await password_input.fill(account.password)
                                        await asyncio.sleep(2)
                                        await page.get_by_text("Log in").click()
                                        await asyncio.sleep(3)
                                        
                                        try:
                                            await page.wait_for_url("https://twitter.com/home", timeout=15000)
                                            logger.info("Login successful with new password on retry")
                                            return
                                        except PlaywrightTimeoutError:
                                            try:
                                                await page.wait_for_url("https://x.com/home", timeout=15000)
                                                logger.info("Login successful with new password on retry")
                                                return
                                            except PlaywrightTimeoutError:
                                                retry_count += 1
                                                continue
                                    
                                    # If we're here, new password failed 3 times
                                    # Try with old password if available
                                    if account.old_password:
                                        logger.info("New password failed 3 times. Attempting login with old password...")
                                        await password_input.fill(account.old_password)
                                        await asyncio.sleep(2)
                                        await page.get_by_text("Log in").click()
                                        await asyncio.sleep(3)
                                        
                                        # Handle 2FA for old password attempt if needed
                                        try:
                                            two_fa_input = await page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=5000)
                                            if two_fa_input and account.two_fa:
                                                two_fa_page = await browser.new_page()
                                                try:
                                                    await two_fa_page.goto(f'https://2fa.fb.rip/{account.two_fa}', timeout=15000)
                                                    await two_fa_page.wait_for_selector('#app', state='visible', timeout=10000)
                                                    verify_code_element = await two_fa_page.wait_for_selector('#verifyCode', timeout=10000)
                                                    if verify_code_element:
                                                        code = await verify_code_element.text_content()
                                                        digits = ''.join(c for c in code if c.isdigit())
                                                        if digits and len(digits) == 6:
                                                            await two_fa_input.fill(digits)
                                                            await asyncio.sleep(2)
                                                            
                                                            # Click Next button (same approach as other steps)
                                                            await page.get_by_text("Next").click()
                                                            
                                                            await asyncio.sleep(3)
                                                finally:
                                                    await two_fa_page.close()
                                        except PlaywrightTimeoutError:
                                            pass
                                        
                                        # Check if login with old password succeeded
                                        try:
                                            await page.wait_for_url("https://twitter.com/home", timeout=15000)
                                            # If we get here, old password worked
                                            # Swap passwords - make old password current and store failed new password as old
                                            temp_password = account.password
                                            account.password = account.old_password
                                            account.old_password = temp_password
                                            await db.commit()
                                            logger.info("Login successful with old password, passwords swapped")
                                            
                                            # Extract cookies since login was successful
                                            cookies = await context.cookies()
                                            ct0 = next((c['value'] for c in cookies if c['name'] == 'ct0'), None)
                                            auth_token = next((c['value'] for c in cookies if c['name'] == 'auth_token'), None)
                                            if not ct0 or not auth_token:
                                                raise Exception("Failed to extract required cookies")
                                            
                                            # Update account with new cookies
                                            account.ct0 = ct0
                                            account.auth_token = auth_token
                                            account.status = 'active'
                                            account.last_validation = 'Cookies refreshed successfully with old password'
                                            account.last_validation_time = datetime.utcnow()
                                            await db.commit()
                                            
                                            return {
                                                "success": True,
                                                "message": "Cookies refreshed successfully with old password",
                                                "ct0": ct0,
                                                "auth_token": auth_token
                                            }
                                        except PlaywrightTimeoutError:
                                            try:
                                                await page.wait_for_url("https://x.com/home", timeout=15000)
                                                # If we get here, old password worked on x.com
                                                temp_password = account.password
                                                account.password = account.old_password
                                                account.old_password = temp_password
                                                await db.commit()
                                                logger.info("Login successful with old password on x.com, passwords swapped")
                                                
                                                # Extract cookies since login was successful
                                                cookies = await context.cookies()
                                                ct0 = next((c['value'] for c in cookies if c['name'] == 'ct0'), None)
                                                auth_token = next((c['value'] for c in cookies if c['name'] == 'auth_token'), None)
                                                if not ct0 or not auth_token:
                                                    raise Exception("Failed to extract required cookies")
                                                
                                                # Update account with new cookies
                                                account.ct0 = ct0
                                                account.auth_token = auth_token
                                                account.status = 'active'
                                                account.last_validation = 'Cookies refreshed successfully with old password'
                                                account.last_validation_time = datetime.utcnow()
                                                await db.commit()
                                                
                                                return {
                                                    "success": True,
                                                    "message": "Cookies refreshed successfully with old password",
                                                    "ct0": ct0,
                                                    "auth_token": auth_token
                                                }
                                            except PlaywrightTimeoutError:
                                                # If old password also failed, raise the original error
                                                raise Exception(f"Login failed with both new password (3 attempts) and old password: {error_text}")
                                    else:
                                        raise Exception(f"Login failed after 3 attempts with new password: {error_text}")
                        except PlaywrightTimeoutError:
                            continue
                    
                except PlaywrightTimeoutError:
                    # No error messages found, continue
                    pass
                except Exception as e:
                    if "Login failed" in str(e):
                        raise e
                    logger.error(f"Error checking for error messages: {str(e)}")

                # Verify login success (handle both twitter.com and x.com)
                try:
                    await page.wait_for_url("https://twitter.com/home", timeout=15000)
                except PlaywrightTimeoutError:
                    try:
                        await page.wait_for_url("https://x.com/home", timeout=15000)
                    except PlaywrightTimeoutError:
                        raise Exception("Login verification failed - could not reach home page")
                
                # Extract cookies
                cookies = await context.cookies()
                ct0 = next((c['value'] for c in cookies if c['name'] == 'ct0'), None)
                auth_token = next((c['value'] for c in cookies if c['name'] == 'auth_token'), None)
                
                if not ct0 or not auth_token:
                    raise Exception("Failed to extract required cookies")
                
                # Update account in database
                account.ct0 = ct0
                account.auth_token = auth_token
                account.status = 'active'  # Reset error status
                account.last_validation = 'Cookies refreshed successfully'
                account.last_validation_time = datetime.utcnow()
                # Clear old_password since login was successful
                account.old_password = None
                await db.commit()

                # Update accounts1.csv file if it exists
                try:
                    import os
                    csv_path = os.path.join(os.getcwd(), 'accounts1.csv')
                    logger.info(f"Looking for CSV at: {csv_path}")
                    if os.path.exists(csv_path):
                        df = pd.read_csv(csv_path)
                        mask = df['account_no'].astype(str) == str(account_no)  # Ensure string comparison
                        if mask.any():
                            df.loc[mask, 'ct0'] = ct0
                            df.loc[mask, 'auth_token'] = auth_token
                            df.to_csv(csv_path, index=False)
                            logger.info(f"Updated accounts1.csv for account {account_no}")
                        else:
                            logger.warning(f"Account {account_no} not found in accounts1.csv (checked {sum(mask)} rows)")
                    else:
                        logger.info(f"accounts1.csv file not found at {csv_path}, skipping CSV update")
                except Exception as e:
                    logger.error(f"Error updating accounts1.csv: {str(e)}")
                
                # Broadcast success with cookies
                await broadcast_message(request, "task_update", {
                    "task_type": "cookie_refresh",
                    "account_no": account_no,
                    "status": "completed",
                    "message": "Successfully refreshed cookies",
                    "cookies": {
                        "ct0": ct0,
                        "auth_token": auth_token
                    }
                })
                
                logger.info(f"Successfully refreshed cookies for account {account_no}")
                return {
                    "success": True,
                    "message": "Cookies refreshed successfully",
                    "ct0": ct0,
                    "auth_token": auth_token
                }
                
            finally:
                await browser.close()
                
    except Exception as e:
        error_msg = f"Error refreshing cookies: {str(e)}"
        logger.error(f"Error refreshing cookies for account {account_no}: {str(e)}")
        
        # Broadcast error
        await broadcast_message(request, "task_update", {
            "task_type": "cookie_refresh",
            "account_no": account_no,
            "status": "failed",
            "error": str(e),
            "message": f"Cookie refresh failed: {str(e)}"
        })
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_msg
        )

@router.post("/import")
async def import_accounts(
    file: UploadFile = File(...),
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
                
                # Set default values for required fields
                account_data['validation_in_progress'] = ValidationState.PENDING
                account_data['oauth_setup_status'] = 'PENDING'  # Set default OAuth status
                account_data['is_active'] = True
                account_data['is_worker'] = account_data.get('act_type') == 'worker'
                account_data['created_at'] = datetime.utcnow()
                account_data['updated_at'] = datetime.utcnow()
                
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

@router.post("/download")
async def download_accounts(
    request: Request,
    accounts: List[str],
    db: AsyncSession = Depends(get_db)
):
    """Download selected accounts as CSV"""
    try:
        result = await db.execute(
            select(Account).where(Account.account_no.in_(accounts))
        )
        selected_accounts = result.scalars().all()
        
        if not selected_accounts:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No accounts found"
            )
            
        # Convert to DataFrame with all fields
        accounts_data = []
        for account in selected_accounts:
            account_dict = {
                col.name: getattr(account, col.name)
                for col in Account.__table__.columns
            }
            accounts_data.append(account_dict)
        
        df = pd.DataFrame(accounts_data)
        
        # Reorder columns to match model definition
        column_order = [
            'account_no', 'act_type', 'login', 'password', 'email', 'email_password',
            'auth_token', 'ct0', 'two_fa', 'proxy_url', 'proxy_port', 'proxy_username',
            'proxy_password', 'user_agent', 'consumer_key', 'consumer_secret',
            'bearer_token', 'access_token', 'access_token_secret', 'client_id',
            'client_secret', 'language_status', 'developer_status', 'unlock_status',
            'is_active', 'is_worker', 'is_suspended', 'credentials_valid',
            'following_count', 'daily_follows', 'total_follows', 'failed_follow_attempts',
            'rate_limit_until', 'current_15min_requests', 'current_24h_requests',
            'last_rate_limit_reset', 'last_followed_at', 'last_login', 'activated_at',
            'last_validation_time', 'last_task_time', 'total_tasks_completed',
            'total_tasks_failed', 'validation_in_progress', 'meta_data',
            'last_validation', 'recovery_attempts', 'recovery_status',
            'last_recovery_time', 'created_at', 'updated_at', 'deleted_at',
            'oauth_setup_status'
        ]
        
        # Ensure all columns exist and reorder
        existing_columns = df.columns.tolist()
        ordered_columns = [col for col in column_order if col in existing_columns]
        df = df[ordered_columns]
        
        # Convert to CSV
        output = io.StringIO()
        df.to_csv(output, index=False)
        
        # Prepare response
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                'Content-Disposition': f'attachment; filename=accounts_export.csv'
            }
        )
    except Exception as e:
        logger.error(f"Error downloading accounts: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.post("/delete/bulk")
async def delete_accounts(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Delete multiple accounts"""
    try:
        # Get accounts from request body
        body = await request.json()
        account_numbers = body.get('accounts', [])
        
        if not account_numbers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No accounts provided"
            )
            
        # Ensure all account numbers are strings
        account_numbers = [str(acc) for acc in account_numbers if acc]
        
        # Get accounts from database
        result = await db.execute(
            select(Account).filter(Account.account_no.in_(account_numbers))
        )
        accounts = result.scalars().all()
        
        if not accounts:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No accounts found"
            )
            
        # Soft delete accounts
        deleted_count = 0
        for account in accounts:
            account.deleted_at = datetime.utcnow()
            deleted_count += 1
            
        await db.commit()
        
        return {
            "status": "success",
            "message": f"Deleted {deleted_count} accounts successfully",
            "deleted_count": deleted_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting accounts: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting accounts: {str(e)}"
        )

@router.delete("/{account_no}")
async def delete_account(
    account_no: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete a specific account"""
    try:
        
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Account {account_no} not found"
            )

        # Soft delete by setting deleted_at
        account.deleted_at = datetime.utcnow()
        
        # Make sure to commit the changes
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to commit changes: {str(e)}"
            )

        return {
            "status": "success",
            "message": f"Account {account_no} deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting account {account_no}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

async def process_account_chunk(db: AsyncSession, accounts: List[dict]) -> tuple[int, List[str]]:
    """Process a chunk of accounts with proper error handling"""
    successful = 0
    errors = []
    
    for account_data in accounts:
        try:
            result = await db.execute(
                select(Account).where(Account.account_no == account_data.get('account_no'))
            )
            existing_account = result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error processing account {account_data.get('account_no')}: {e}")
            continue

        try:
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
                if existing_account.validation_in_progress != ValidationState.VALIDATING:
                    existing_account.validation_in_progress = ValidationState.COMPLETED
            else:
                # Create new account
                account_data['created_at'] = datetime.utcnow()
                
                # Set worker flag based on act_type from CSV
                account_data['is_worker'] = account_data.get('act_type') == 'worker'
                account_data['is_active'] = True
                account_data['validation_in_progress'] = ValidationState.COMPLETED
                
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

@router.get("/all-account-numbers")
async def get_all_account_numbers(
    db: AsyncSession = Depends(get_db),
    search: Optional[str] = None
):
    """Get all account numbers for bulk selection"""
    try:
        # Build base query
        query = select(Account.account_no).filter(Account.deleted_at.is_(None))
        
        # Add search filter if provided
        if search:
            query = query.where(
                or_(
                    Account.account_no.ilike(f"%{search}%"),
                    Account.login.ilike(f"%{search}%"),
                    Account.email.ilike(f"%{search}%")
                )
            )
        
        # Execute query
        result = await db.execute(query.order_by(Account.created_at.desc()))
        account_numbers = result.scalars().all()
        
        return {"account_numbers": account_numbers}
    except Exception as e:
        logger.error(f"Error fetching account numbers: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
