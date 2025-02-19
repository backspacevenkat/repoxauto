import asyncio
import logging
import os
import random
import string
import secrets
import json
from datetime import datetime
from typing import Dict, Optional, Tuple
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from sqlalchemy import select
from ..services.twitter_client import construct_proxy_url
from ..database import db_manager
from ..models.account import Account

# Constants for timeouts and retries
BROWSER_TIMEOUT = 180000  # 3 minutes for browser operations
PAGE_TIMEOUT = 120000     # 2 minutes for page operations
PAGE_LOAD_RETRIES = 6     # Number of retries for page load
PORT_RETRY_ATTEMPTS = 3   # Reduced number of retries for quicker rotation
PORT_RETRY_DELAY = 60     # Increased base delay between port retries to 1 minute
MAX_BACKOFF_DELAY = 300   # Maximum backoff delay in seconds
RATE_LIMIT_DELAY = 60     # Increased base delay between operations to 1 minute
LOGIN_TIMEOUT = 60000     # 60 seconds for login operations
PASSWORD_CHANGE_TIMEOUT = 120000  # 2 minutes for password change
VERIFICATION_TIMEOUT = 120000     # 2 minutes for verification steps
TWO_FA_TIMEOUT = 60000          # 60 seconds for 2FA operations

# Batch processing constants
DEFAULT_THREADS = 6       # Default number of threads from frontend
BATCH_SIZE = 6           # Match batch size to default thread count
BATCH_COOLDOWN = 300     # 5 minutes between batches
MIN_BATCH_DELAY = 60     # Minimum 1 minute delay between batches

# Port retry constants
MAX_PORT_INCREMENT = 10  # Try up to 10 port increments
PORT_SWITCH_DELAY = 60   # 1 minute delay between port switches

# Output directory setup
OUTPUT_FOLDER = 'output'
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Configure main logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("password_manager.log"),
        logging.StreamHandler()
    ]
)

# Configure password logging
password_logger = logging.getLogger('password_logger')
password_logger.setLevel(logging.INFO)
password_handler = logging.FileHandler('password_changes.log')
password_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
password_logger.addHandler(password_handler)

logger = logging.getLogger(__name__)

def generate_secure_password(length: int = 20) -> str:
    """Generate a secure random password with timestamp"""
    lowercase = string.ascii_lowercase
    uppercase = string.ascii_uppercase
    digits = string.digits
    symbols = "!@#$%^&*"
    
    # Ensure at least one of each character type
    password = [
        secrets.choice(lowercase),
        secrets.choice(uppercase),
        secrets.choice(digits),
        secrets.choice(symbols)
    ]
    
    # Fill remaining length with random characters
    all_characters = lowercase + uppercase + digits + symbols
    password.extend(secrets.choice(all_characters) for _ in range(length - 4))
    
    # Shuffle to make it random
    password_list = list(password)
    secrets.SystemRandom().shuffle(password_list)
    
    # Add timestamp
    timestamp = datetime.now().strftime('%Y%m%d')
    return f"{''.join(password_list)}_{timestamp}"

class PasswordManager:
    def __init__(self, account_data: Dict):
        self.account_data = account_data.copy()
        self.account_no = account_data['account_no']
        self.proxy_config = None
        self.new_password = None
        self.old_password = None
        self.old_cookies = None
        self.new_cookies = None
        self.browser = None
        self.context = None
        self.playwright = None

    async def goto_with_retry(self, page, url: str, max_retries: int = PAGE_LOAD_RETRIES) -> bool:
        """Navigate to URL with retry mechanism and exponential backoff"""
        for attempt in range(max_retries):
            try:
                timeout = PAGE_TIMEOUT * (attempt + 1)  # Increase timeout with each retry
                logger.info(f"Attempting to navigate to {url} (attempt {attempt + 1}/{max_retries}, timeout: {timeout}ms)")
                
                # Add pre-navigation delay with exponential backoff
                if attempt > 0:
                    backoff_delay = min(RATE_LIMIT_DELAY * (2 ** (attempt - 1)), MAX_BACKOFF_DELAY)
                    logger.info(f"Pre-navigation delay: {backoff_delay} seconds")
                    await asyncio.sleep(backoff_delay)
                
                # Attempt navigation
                await page.goto(url, timeout=timeout)
                
                # Verify page load
                try:
                    await page.wait_for_load_state('domcontentloaded', timeout=timeout)
                    await page.wait_for_load_state('networkidle', timeout=timeout)
                    
                    # Check document ready state
                    ready_state = await page.evaluate("document.readyState")
                    if ready_state != 'complete':
                        raise Exception("Document not fully loaded")
                        
                    # Test basic page interactivity
                    await page.evaluate("window.innerWidth")
                    await page.evaluate("document.body.scrollHeight")
                    
                    logger.info(f"Successfully loaded {url}")
                    return True
                    
                except Exception as e:
                    logger.warning(f"Page load verification failed: {str(e)}")
                    raise
                    
            except Exception as e:
                logger.warning(f"Navigation attempt {attempt + 1} failed: {str(e)}")
                if attempt == max_retries - 1:
                    logger.error(f"All navigation attempts failed for {url}")
                    raise
                
                backoff_delay = min(RATE_LIMIT_DELAY * (2 ** attempt), MAX_BACKOFF_DELAY)
                logger.info(f"Waiting {backoff_delay} seconds before retry...")
                await asyncio.sleep(backoff_delay)
                
        return False

    async def setup_browser_context(self, use_new_credentials: bool = False) -> Optional[Tuple]:
        """Sets up Playwright browser with proxy and cookies, with port retry logic"""
        initial_port = self.account_data['proxy_port']
        initial_error = None

        for port_increment in range(MAX_PORT_INCREMENT):
            try:
                # Clean up any existing resources
                await self.cleanup_resources()

                # Calculate new port
                current_port = str(int(initial_port) + port_increment)
                logger.info(f"Attempting setup with port {current_port} (increment {port_increment})")

                if all(self.account_data.get(k) for k in ['proxy_url', 'proxy_username', 'proxy_password']):
                    # Update proxy configuration with new port
                    encoded_proxy_url = construct_proxy_url(
                        self.account_data['proxy_username'],
                        self.account_data['proxy_password'],
                        self.account_data['proxy_url'],
                        current_port
                    )
                    
                    self.proxy_config = {
                        'server': f"http://{self.account_data['proxy_url']}:{current_port}",
                        'username': str(self.account_data['proxy_username']),
                        'password': str(self.account_data['proxy_password'])
                    }

                self.playwright = await async_playwright().start()
                
                # Launch browser with enhanced configuration
                self.browser = await self.playwright.chromium.launch(
                    headless=True,
                    proxy=self.proxy_config,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-accelerated-2d-canvas',
                        '--disable-gpu',
                        '--window-size=1280,800',
                        '--disable-features=IsolateOrigins,site-per-process', # Disable site isolation
                        '--disable-web-security', # Disable CORS
                        '--disable-features=NetworkService' # Use old network stack
                    ]
                )
                
                # Create context with enhanced configuration
                self.context = await self.browser.new_context(
                    user_agent=self.account_data.get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'),
                    viewport={'width': 1280, 'height': 800},
                    ignore_https_errors=True,
                    java_script_enabled=True,
                    bypass_csp=True,
                    proxy=self.proxy_config,
                    extra_http_headers={'Accept-Language': 'en-US,en;q=0.9'} # Set language header
                )
                
                # Set cookies based on credentials
                auth_token = self.new_cookies['auth_token'] if use_new_credentials and self.new_cookies else self.account_data['auth_token']
                ct0 = self.new_cookies['ct0'] if use_new_credentials and self.new_cookies else self.account_data['ct0']
                
                await self.context.add_cookies([
                    {
                        'name': 'ct0',
                        'value': ct0,
                        'domain': '.twitter.com',
                        'path': '/',
                        'secure': True,
                        'sameSite': 'Lax'
                    },
                    {
                        'name': 'auth_token',
                        'value': auth_token,
                        'domain': '.twitter.com',
                        'path': '/',
                        'secure': True,
                        'sameSite': 'Lax'
                    }
                ])

                # Test the setup
                test_page = await self.context.new_page()
                try:
                    await test_page.goto('about:blank', timeout=30000)
                    await test_page.evaluate("window.innerWidth")
                    logger.info(f"Successfully set up browser with port {current_port}")
                    return self.playwright, self.browser, self.context
                finally:
                    if test_page:
                        await test_page.close()
                    
            except Exception as e:
                logger.error(f"Setup failed with port {current_port}: {str(e)}")
                if not initial_error:
                    initial_error = e
                await self.cleanup_resources()
                
                if port_increment < MAX_PORT_INCREMENT - 1:
                    logger.info(f"Waiting {PORT_SWITCH_DELAY} seconds before trying next port")
                    await asyncio.sleep(PORT_SWITCH_DELAY)
                continue

        # If all retries failed, log the initial error
        if initial_error:
            logger.error(f"All port attempts failed. Initial error: {str(initial_error)}")
        return None, None, None

    async def cleanup_resources(self):
        """Clean up browser resources"""
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.error(f"Error cleaning up resources: {str(e)}")
        finally:
            self.context = None
            self.browser = None
            self.playwright = None

    async def get_2fa_code(self, two_fa_value: str) -> str:
        """
        Open a new page to navigate to the 2FA service and extract the six-digit code.
        Retries are handled via the caller if needed.
        """
        if not two_fa_value:
            raise Exception("2FA is required but no two_fa token provided in account data")
        logger.info(f"Opening 2FA page with token: '{two_fa_value}'")
        two_fa_page = await self.browser.new_page()
        try:
            await two_fa_page.goto(f'https://2fa.fb.rip/{two_fa_value}', timeout=15000)
            await two_fa_page.wait_for_selector('#app', state='visible', timeout=10000)
            verify_code_element = await two_fa_page.wait_for_selector('#verifyCode', timeout=10000)
            if verify_code_element:
                code = await verify_code_element.text_content()
                digits = ''.join(c for c in code if c.isdigit())
                if digits and len(digits) == 6:
                    logger.info(f"Retrieved 2FA code: {digits}")
                    return digits
                else:
                    # Optionally, capture a screenshot for debugging.
                    await two_fa_page.screenshot(path="2fa_invalid_code.png")
                    raise Exception("Invalid 2FA code format from service")
            else:
                raise Exception("Could not find 2FA code element on 2FA page")
        except Exception as e:
            logger.error(f"Error retrieving 2FA code: {e}")
            # Optionally, capture a screenshot for debugging.
            await two_fa_page.screenshot(path="2fa_error.png")
            raise Exception("Timeout or error waiting for 2FA code from service") from e
        finally:
            await two_fa_page.close()


    async def verify_new_password(self, existing_context) -> bool:
        """
        Verify new password by logging in – with 2FA handling that ALWAYS opens https://2fa.fb.rip/ in a new tab
        if a 2FA prompt appears, even if the two_fa token is missing or empty.
        """
        page = None
        try:
            if not existing_context:
                return False

            page = await existing_context.new_page()
            logger.info("Starting login verification process...")

            # 1) Navigate to Twitter login flow
            await self.goto_with_retry(page, 'https://twitter.com/i/flow/login')

            # 2) Enter username
            username_input = None
            for selector in ['input[autocomplete="username"]', 'input[name="text"]', 'input[type="text"]']:
                try:
                    username_input = await page.wait_for_selector(selector, timeout=LOGIN_TIMEOUT, state='visible')
                    if username_input:
                        break
                except Exception:
                    continue
            if not username_input:
                raise Exception("Could not find username input field for new password login")
            await username_input.fill(self.account_data['login'])
            await asyncio.sleep(2)
            await page.get_by_text("Next").click()
            await asyncio.sleep(2)

            # 3) Enter new password
            password_input = None
            for selector in ['input[name="password"]', 'input[type="password"]']:
                try:
                    password_input = await page.wait_for_selector(selector, timeout=LOGIN_TIMEOUT, state='visible')
                    if password_input:
                        break
                except Exception:
                    continue
            if not password_input:
                raise Exception("Could not find password input field for new password login")
            await password_input.fill(self.new_password)
            await asyncio.sleep(2)

            # 4) Click "Log in"
            try:
                await page.get_by_text("Log in", exact=True).click()
            except Exception:
                try:
                    await page.get_by_role("button", name="Log in").click()
                except Exception:
                    await page.locator('[data-testid="LoginButton"]').click()
            await asyncio.sleep(3)

            # 5) 2FA handling (ALWAYS open https://2fa.fb.rip/, even if token is missing)
            try:
                two_fa_input = await page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=5000)
                if two_fa_input:
                    # Grab the two_fa token (may be empty)
                    two_fa_value = self.account_data.get('two_fa', '')
                    if not two_fa_value:
                        logger.warning("2FA prompt appeared, but two_fa token is missing or empty. Opening 2FA page anyway.")

                    # Open a new tab and attempt to retrieve the code
                    two_fa_page = await self.browser.new_page()
                    try:
                        two_fa_url = f'https://2fa.fb.rip/{two_fa_value}'
                        logger.info(f"Navigating to 2FA page: {two_fa_url}")
                        await two_fa_page.goto(two_fa_url, timeout=15000)
                        await two_fa_page.wait_for_selector('#app', state='visible', timeout=10000)

                        verify_code_element = await two_fa_page.wait_for_selector('#verifyCode', timeout=10000)
                        if verify_code_element:
                            code = await verify_code_element.text_content()
                            digits = ''.join(c for c in code if c.isdigit())
                            if digits and len(digits) == 6:
                                logger.info(f"Retrieved 2FA code for new password login: {digits}")
                                await two_fa_input.fill(digits)
                                await asyncio.sleep(2)
                                await page.get_by_text("Next").click()
                                await asyncio.sleep(3)
                            else:
                                logger.warning("Did not retrieve a valid 6-digit code (token may be empty or invalid).")
                        else:
                            logger.warning("Could not find #verifyCode element on the 2FA page.")
                    finally:
                        await two_fa_page.close()
            except asyncio.TimeoutError:
                # No 2FA prompt found, continue
                pass
            except PlaywrightTimeoutError:
                # Same as above, no 2FA prompt found
                pass

            # 6) Check for any error messages
            for selector in ['[data-testid="error-detail"]', '.alert-message', '.error-text', '[role="alert"]']:
                try:
                    error_element = await page.wait_for_selector(selector, timeout=2000)
                    if error_element:
                        error_text = await error_element.text_content()
                        if error_text:
                            await page.screenshot(path=f"output/error_new_password_{self.account_no}.png")
                            raise Exception(f"Login failed with new password: {error_text}")
                except PlaywrightTimeoutError:
                    continue

            # 7) Verify success (look for home URL on Twitter or X)
            try:
                await page.wait_for_url("https://twitter.com/home", timeout=15000)
            except Exception:
                try:
                    await page.wait_for_url("https://x.com/home", timeout=15000)
                except Exception:
                    logger.warning(f"Login with new password failed. Current URL: {page.url}")
                    await page.screenshot(path=f"output/login_failed_new_{self.account_no}.png")

                    # --- Fallback: old password login ---
                    logger.info("Attempting login with old password...")
                    await self.goto_with_retry(page, 'https://twitter.com/i/flow/login')

                    # Enter username again
                    username_input = None
                    for selector in ['input[autocomplete="username"]', 'input[name="text"]', 'input[type="text"]']:
                        try:
                            username_input = await page.wait_for_selector(selector, timeout=LOGIN_TIMEOUT, state='visible')
                            if username_input:
                                break
                        except Exception:
                            continue
                    if not username_input:
                        raise Exception("Could not find username input field for old password login")
                    await username_input.fill(self.account_data['login'])
                    await asyncio.sleep(2)
                    await page.get_by_text("Next").click()
                    await asyncio.sleep(2)

                    # Enter old password
                    password_input = None
                    for selector in ['input[name="password"]', 'input[type="password"]']:
                        try:
                            password_input = await page.wait_for_selector(selector, timeout=LOGIN_TIMEOUT, state='visible')
                            if password_input:
                                break
                        except Exception:
                            continue
                    if not password_input:
                        raise Exception("Could not find password input field for old password login")
                    await password_input.fill(self.old_password)
                    await asyncio.sleep(2)
                    try:
                        await page.get_by_text("Log in", exact=True).click()
                    except Exception:
                        try:
                            await page.get_by_role("button", name="Log in").click()
                        except Exception:
                            await page.locator('[data-testid="LoginButton"]').click()
                    await asyncio.sleep(3)

                    # 2FA for old password (ALWAYS open page, even if empty token)
                    try:
                        two_fa_input = await page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=5000)
                        if two_fa_input:
                            two_fa_value = self.account_data.get('two_fa', '')
                            if not two_fa_value:
                                logger.warning("2FA prompt for old password login, but token is missing or empty.")
                            two_fa_page = await self.browser.new_page()
                            try:
                                two_fa_url = f'https://2fa.fb.rip/{two_fa_value}'
                                logger.info(f"Navigating to 2FA page for old password: {two_fa_url}")
                                await two_fa_page.goto(two_fa_url, timeout=15000)
                                await two_fa_page.wait_for_selector('#app', state='visible', timeout=10000)

                                verify_code_element = await two_fa_page.wait_for_selector('#verifyCode', timeout=10000)
                                if verify_code_element:
                                    code = await verify_code_element.text_content()
                                    digits = ''.join(c for c in code if c.isdigit())
                                    if digits and len(digits) == 6:
                                        logger.info(f"Retrieved 2FA code for old password login: {digits}")
                                        await two_fa_input.fill(digits)
                                        await asyncio.sleep(2)
                                        await page.get_by_text("Next").click()
                                        await asyncio.sleep(3)
                                    else:
                                        logger.warning("Did not retrieve a valid 6-digit code (token may be empty or invalid).")
                                else:
                                    logger.warning("Could not find #verifyCode element (old password login).")
                            finally:
                                await two_fa_page.close()
                    except (PlaywrightTimeoutError, asyncio.TimeoutError):
                        pass

                    # Verify old password login success
                    try:
                        await page.wait_for_url("https://twitter.com/home", timeout=15000)
                    except Exception:
                        try:
                            await page.wait_for_url("https://x.com/home", timeout=15000)
                        except Exception:
                            logger.error(f"Login with old password also failed. Current URL: {page.url}")
                            await page.screenshot(path=f"output/login_failed_old_{self.account_no}.png")
                            return False

                    # If old password login succeeded, revert in DB
                    session = db_manager.async_session()
                    try:
                        result = await session.execute(
                            select(Account).filter(Account.account_no == self.account_no)
                        )
                        account = result.scalar_one_or_none()
                        if account:
                            account.password = account.old_password
                            account.old_password = None
                            await session.commit()
                            logger.info("Reverted to old password in database")
                    except Exception as e:
                        await session.rollback()
                        logger.error(f"Error reverting password in database: {str(e)}")
                    finally:
                        await session.close()

                    return False

            # If we get here, new password login was successful
            cookies = await existing_context.cookies()
            self.new_cookies = {
                'ct0': next((c['value'] for c in cookies if c['name'] == 'ct0'), None),
                'auth_token': next((c['value'] for c in cookies if c['name'] == 'auth_token'), None)
            }
            if not all(self.new_cookies.values()):
                logger.error("Failed to extract new cookies after new password login")
                return False

            logger.info("Successfully verified new password and obtained new cookies")
            return True

        except Exception as e:
            logger.error(f"Error in verify_new_password: {str(e)}")
            return False
        finally:
            if page:
                await page.close()


    async def update_password(
        self,
        semaphore: Optional[asyncio.Semaphore] = None,
        batch_index: int = 0,
        total_batches: int = 1
    ) -> Dict:
        """Update password with retry logic and port switching"""
        try:
            # Add progressive delay based on batch position
            if batch_index > 0:
                # Progressive delay: each batch waits longer than the previous one
                delay = min(MIN_BATCH_DELAY * (batch_index + 1), BATCH_COOLDOWN)
                logger.info(f"Batch {batch_index}/{total_batches}: Progressive delay {delay}s before starting")
                await asyncio.sleep(delay)
            # Check if password is already complete (length > 20)
            if self.account_data.get('password') and len(self.account_data['password']) > 20:
                logger.info(f"Account {self.account_no} already has a complete password, skipping update")
                return {
                    'success': True,
                    'message': 'Password already complete, skipping update'
                }

            initial_error = None
            # Store current credentials
            self.old_password = self.account_data['password']
            self.new_password = generate_secure_password()
            self.old_cookies = {
                'ct0': self.account_data['ct0'],
                'auth_token': self.account_data['auth_token']
            }

            # Update database first
            session = db_manager.async_session()
            try:
                result = await session.execute(
                    select(Account).filter(Account.account_no == self.account_no)
                )
                account = result.scalar_one_or_none()
                
                if not account:
                    return {
                        'success': False,
                        'message': 'Account not found in database'
                    }
                
                account.old_password = self.old_password
                account.password = self.new_password
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"Database error: {str(e)}")
                return {
                    'success': False,
                    'message': f'Database error: {str(e)}'
                }
            finally:
                await session.close()
            
            logger.info(f"Starting password change for account {self.account_no}")
            
            async with semaphore if semaphore else asyncio.nullcontext():
                # Try with different ports
                for port_increment in range(MAX_PORT_INCREMENT):
                    page = None
                    try:
                        current_port = str(int(self.account_data['proxy_port']) + port_increment)
                        self.account_data['proxy_port'] = current_port
                        logger.info(f"Attempting with port {current_port} (increment {port_increment})")
                        
                        setup = await self.setup_browser_context()
                        if not all(setup):
                            logger.error(f"Failed to setup browser with port {current_port}")
                            continue
                        
                        page = await self.context.new_page()
                        
                        # Navigate to password change page with enhanced retry logic
                        try:
                            if not await self.goto_with_retry(page, 'https://x.com/settings/password'):
                                logger.error(f"Failed to navigate to password change page with port {current_port}")
                                await page.screenshot(path=f"output/navigation_failed_{self.account_no}_{current_port}.png")
                                continue
                            
                            # Verify page load and check for redirects
                            current_url = page.url.lower()
                            if 'login' in current_url:
                                logger.error(f"Not logged in with port {current_port}, cookies might be expired")
                                await page.screenshot(path=f"output/login_redirect_{self.account_no}_{current_port}.png")
                                continue
                            
                            # Save page state for debugging
                            await page.screenshot(path=f"output/password_page_{self.account_no}_{current_port}.png")
                            html_content = await page.content()
                            with open(f"output/password_page_{self.account_no}_{current_port}.html", "w", encoding="utf-8") as f:
                                f.write(html_content)
                        except Exception as e:
                            logger.error(f"Navigation error with port {current_port}: {str(e)}")
                            continue
                        
                        # Fill password change form with enhanced retry logic
                        form_filled = False
                        for attempt in range(PORT_RETRY_ATTEMPTS):
                            try:
                                # Wait for form fields with explicit timeouts
                                current_password = await page.wait_for_selector('input[name="current_password"]', timeout=PAGE_TIMEOUT)
                                new_password = await page.wait_for_selector('input[name="new_password"]', timeout=PAGE_TIMEOUT)
                                confirm_password = await page.wait_for_selector('input[name="password_confirmation"]', timeout=PAGE_TIMEOUT)
                                
                                if all([current_password, new_password, confirm_password]):
                                    # Fill fields with delays and verification
                                    await current_password.fill(self.old_password)
                                    await asyncio.sleep(2)
                                    current_value = await current_password.input_value()
                                    if current_value != self.old_password:
                                        raise Exception("Current password field verification failed")
                                    
                                    await new_password.fill(self.new_password)
                                    await asyncio.sleep(2)
                                    new_value = await new_password.input_value()
                                    if new_value != self.new_password:
                                        raise Exception("New password field verification failed")
                                    
                                    await confirm_password.fill(self.new_password)
                                    await asyncio.sleep(2)
                                    confirm_value = await confirm_password.input_value()
                                    if confirm_value != self.new_password:
                                        raise Exception("Confirm password field verification failed")
                                    
                                    # Take screenshot after filling form
                                    await page.screenshot(path=f"output/form_filled_{self.account_no}_{current_port}.png")
                                    form_filled = True
                                    break
                            except Exception as e:
                                logger.warning(f"Form fill attempt {attempt + 1} failed: {str(e)}")
                                if attempt < PORT_RETRY_ATTEMPTS - 1:
                                    backoff_delay = min(PORT_RETRY_DELAY * (2 ** attempt), MAX_BACKOFF_DELAY)
                                    await asyncio.sleep(backoff_delay)
                                continue
                        
                        if not form_filled:
                            logger.error(f"Failed to fill form with port {current_port}")
                            continue
                        
                        # Click save button with enhanced retry logic
                        save_clicked = False
                        for attempt in range(PORT_RETRY_ATTEMPTS):
                            try:
                                # Try multiple selectors for save button
                                save_button = None
                                for selector in [
                                    'span:has-text("Save")',
                                    'button:has-text("Save")',
                                    '[data-testid="settingsDetailSave"]',
                                    '[role="button"]:has-text("Save")'
                                ]:
                                    try:
                                        save_button = await page.wait_for_selector(selector, timeout=PAGE_TIMEOUT)
                                        if save_button and await save_button.is_visible() and await save_button.is_enabled():
                                            logger.info(f"Found save button with selector: {selector}")
                                            break
                                    except Exception:
                                        continue

                                if not save_button:
                                    raise Exception("Could not find save button with any selector")

                                # Take screenshot before clicking
                                await page.screenshot(path=f"output/before_save_{self.account_no}_{current_port}.png")

                                # Ensure button is visible and clickable
                                await save_button.scroll_into_view_if_needed()
                                await asyncio.sleep(2)

                                # Try different click methods
                                try:
                                    await save_button.click()
                                except Exception:
                                    try:
                                        # Try force click if normal click fails
                                        await save_button.click(force=True)
                                    except Exception:
                                        # Try JavaScript click as last resort
                                        await page.evaluate("arguments[0].click()", save_button)

                                # Take screenshot after clicking
                                await page.screenshot(path=f"output/after_save_{self.account_no}_{current_port}.png")
                                save_clicked = True
                                break
                            except Exception as e:
                                logger.warning(f"Save button click attempt {attempt + 1} failed: {str(e)}")
                                if attempt < PORT_RETRY_ATTEMPTS - 1:
                                    backoff_delay = min(PORT_RETRY_DELAY * (2 ** attempt), MAX_BACKOFF_DELAY)
                                    await asyncio.sleep(backoff_delay)
                                continue
                        
                        if not save_clicked:
                            logger.error(f"Failed to click save button with port {current_port}")
                            continue
                        
                        # Wait for save completion with enhanced error handling
                        try:
                            # Wait for network idle
                            await page.wait_for_load_state('networkidle', timeout=PASSWORD_CHANGE_TIMEOUT)
                            
                            # Check for error messages after save
                            error_selectors = [
                                '[data-testid="error-detail"]',
                                '.alert-message',
                                '.error-text',
                                '[role="alert"]',
                                'div:has-text("Something went wrong")',
                                'div:has-text("Please try again")'
                            ]
                            
                            for selector in error_selectors:
                                try:
                                    error_element = await page.wait_for_selector(selector, timeout=2000)
                                    if error_element:
                                        error_text = await error_element.text_content()
                                        if error_text:
                                            # Save error state
                                            await page.screenshot(path=f"output/save_error_{self.account_no}_{current_port}.png")
                                            html_content = await page.content()
                                            with open(f"output/save_error_{self.account_no}_{current_port}.html", "w", encoding="utf-8") as f:
                                                f.write(html_content)
                                            raise Exception(f"Save failed: {error_text}")
                                except PlaywrightTimeoutError:
                                    continue
                            
                            # Check for success messages
                            success_selectors = [
                                'div:has-text("Your password has been changed")',
                                'div:has-text("Password updated successfully")',
                                '[data-testid="toast"]',
                                '.success-message',
                                '[role="status"]:has-text("success")'
                            ]
                            
                            success_found = False
                            for selector in success_selectors:
                                try:
                                    success_element = await page.wait_for_selector(selector, timeout=5000)
                                    if success_element:
                                        success_text = await success_element.text_content()
                                        if success_text:
                                            logger.info(f"Found success message: {success_text}")
                                            success_found = True
                                            break
                                except PlaywrightTimeoutError:
                                    continue
                            
                            # Wait additional time for any post-save operations
                            await asyncio.sleep(5)
                            
                            # Take final screenshot and save page state
                            await page.screenshot(path=f"output/save_complete_{self.account_no}_{current_port}.png")
                            html_content = await page.content()
                            with open(f"output/save_complete_{self.account_no}_{current_port}.html", "w", encoding="utf-8") as f:
                                f.write(html_content)
                            
                            if not success_found:
                                logger.warning("No explicit success message found, proceeding with verification")
                            
                        except Exception as e:
                            logger.error(f"Error during or after save: {str(e)}")
                            continue
                        
                        # Verify new password
                        verification_success = False
                        for attempt in range(PORT_RETRY_ATTEMPTS):
                            try:
                                if await self.verify_new_password(self.context):
                                    verification_success = True
                                    break
                                logger.warning(f"Password verification attempt {attempt + 1} failed")
                                if attempt < PORT_RETRY_ATTEMPTS - 1:
                                    backoff_delay = min(PORT_RETRY_DELAY * (2 ** attempt), MAX_BACKOFF_DELAY)
                                    await asyncio.sleep(backoff_delay)
                            except Exception as e:
                                logger.error(f"Verification attempt {attempt + 1} failed: {str(e)}")
                                if attempt < PORT_RETRY_ATTEMPTS - 1:
                                    backoff_delay = min(PORT_RETRY_DELAY * (2 ** attempt), MAX_BACKOFF_DELAY)
                                    await asyncio.sleep(backoff_delay)
                                continue

                        if verification_success:
                            # Log successful password change
                            password_logger.info(f"Account: {self.account_no}")
                            password_logger.info(f"Old password: {self.old_password}")
                            password_logger.info(f"New password: {self.new_password}")
                            password_logger.info(f"New ct0: {self.new_cookies['ct0']}")
                            password_logger.info(f"New auth_token: {self.new_cookies['auth_token']}")
                            
                            return {
                                'success': True,
                                'new_credentials': {
                                    'password': self.new_password,
                                    'ct0': self.new_cookies['ct0'],
                                    'auth_token': self.new_cookies['auth_token']
                                }
                            }

                    except Exception as e:
                        if not initial_error:
                            initial_error = e
                        logger.error(f"Error during port attempt {port_increment}: {str(e)}")
                    finally:
                        if page:
                            await page.close()
                        await self.cleanup_resources()
                        
                        if port_increment < MAX_PORT_INCREMENT - 1:
                            logger.info(f"Waiting {PORT_SWITCH_DELAY} seconds before trying next port")
                            await asyncio.sleep(PORT_SWITCH_DELAY)

                # If we get here, all port attempts failed
                if initial_error:
                    return {
                        'success': False,
                        'message': f'All port attempts failed. Initial error: {str(initial_error)}'
                    }
                
                return {
                    'success': False,
                    'message': 'All port attempts failed without specific error'
                }

        except Exception as e:
            logger.error(f"Fatal error in update_password: {str(e)}")
            return {
                'success': False,
                'message': f'Fatal error: {str(e)}'
            }

    async def _run_browser_tests(self, test_page) -> bool:
        """Run browser tests on a given page"""
        try:
            # Test navigation
            try:
                if not await self.goto_with_retry(test_page, 'about:blank'):
                    logger.error("Navigation test failed")
                    return False
            except Exception as e:
                logger.error(f"Navigation test failed: {str(e)}")
                return False

            # Test JavaScript execution
            try:
                await test_page.evaluate("window.innerWidth")
                await test_page.evaluate("document.body.scrollHeight")
            except Exception as e:
                logger.error(f"JavaScript execution test failed: {str(e)}")
                return False
            
            logger.info(f"Browser setup test passed for account {self.account_no}")
            return True
        except Exception as e:
            logger.error(f"Browser test operations failed: {str(e)}")
            return False

    async def test_browser_setup(self) -> bool:
        """Test browser setup and basic functionality"""
        test_page = None
        try:
            # Setup browser with timeout
            setup = await asyncio.wait_for(
                self.setup_browser_context(),
                timeout=BROWSER_TIMEOUT / 1000  # Convert to seconds
            )
            if not all(setup):
                logger.error("Browser setup failed: incomplete setup")
                return False

            # Test page creation and operations
            test_page = await self.context.new_page()
            return await self._run_browser_tests(test_page)

        except asyncio.TimeoutError:
            logger.error("Browser setup test timed out")
            return False
        except Exception as e:
            logger.error(f"Browser setup test failed: {str(e)}")
            return False
        finally:
            if test_page:
                try:
                    await test_page.close()
                except Exception:
                    pass
            await self.cleanup_resources()

    async def validate_account_status(self, page) -> bool:
        """Validate account status and detect common issues"""
        try:
            # Check for login page redirect
            if 'login' in page.url:
                logger.error("Account requires login")
                return False
            
            # Check for account suspension
            suspension_selector = 'h1:has-text("Account suspended")'
            try:
                is_suspended = await page.wait_for_selector(suspension_selector, timeout=5000)
                if is_suspended:
                    logger.error("Account is suspended")
                    return False
            except PlaywrightTimeoutError:
                pass  # No suspension message found
            
            # Check for lock/restriction
            lock_selector = 'div:has-text("Account locked")'
            try:
                is_locked = await page.wait_for_selector(lock_selector, timeout=5000)
                if is_locked:
                    logger.error("Account is locked")
                    return False
            except PlaywrightTimeoutError:
                pass  # No lock message found
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating account status: {str(e)}")
            return False
