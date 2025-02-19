import asyncio
import logging
import os
import random
import string
import secrets
import json
import sys
from datetime import datetime
from typing import Dict, Optional, Tuple
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import pandas as pd
from filelock import FileLock

# Configure main logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("twitter_manager.log"),
        logging.StreamHandler()
    ]
)

# Configure password logging
password_logger = logging.getLogger('password_logger')
password_logger.setLevel(logging.INFO)
password_handler = logging.FileHandler('password_changes.log')
password_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
password_logger.addHandler(password_handler)

# Constants
ACCOUNTS_FILE = 'accounts6.csv'
OUTPUT_FOLDER = 'output'
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

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

class TwitterAccountManager:
    def __init__(self, account_data: Dict):
        self.account_data = account_data.copy()
        self.account_no = account_data['account_no']
        self.proxy_config = None
        self.new_password = None
        self.old_password = None
        self.old_cookies = None
        self.new_cookies = None

    async def setup_browser_context(self, use_new_credentials: bool = False):
        """Sets up Playwright browser with proxy and cookies"""
        try:
            # Setup proxy configuration
            if all(self.account_data.get(k) for k in ['proxy_url', 'proxy_port', 'proxy_username', 'proxy_password']):
                proxy_username = quote_plus(self.account_data['proxy_username'])
                proxy_password = quote_plus(self.account_data['proxy_password'])
                self.proxy_config = {
                    'server': f"http://{self.account_data['proxy_url']}:{self.account_data['proxy_port']}",
                    'username': proxy_username,
                    'password': proxy_password
                }

            p = await async_playwright().start()
            browser = await p.chromium.launch(
                headless=True,
                proxy=self.proxy_config,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            
            context = await browser.new_context(
                user_agent=self.account_data.get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
                viewport={'width': 1280, 'height': 800},
                ignore_https_errors=True
            )
            
            # Set cookies based on whether to use new or old credentials
            auth_token = self.new_cookies['auth_token'] if use_new_credentials and self.new_cookies else self.account_data['auth_token']
            ct0 = self.new_cookies['ct0'] if use_new_credentials and self.new_cookies else self.account_data['ct0']
            
            await context.add_cookies([
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
            
            return p, browser, context
            
        except Exception as e:
            logging.error(f"Error setting up browser: {str(e)}")
            return None, None, None

    async def get_2fa_code(self, generator_code: str, browser) -> Optional[str]:
        """Get 2FA code using browser automation"""
        page = None
        try:
            page = await browser.new_page()
            url = f'https://2fa.fb.rip/{generator_code}'
            logging.info(f"Getting 2FA code from {url}")
            
            await page.goto(url, wait_until='networkidle')
            await page.wait_for_selector('#app', state='visible', timeout=10000)
            
            verify_code_element = await page.wait_for_selector('#verifyCode', timeout=10000)
            if verify_code_element:
                code = await verify_code_element.text_content()
                digits = ''.join(c for c in code if c.isdigit())
                if digits and len(digits) == 6:
                    logging.info(f"Successfully got 2FA code: {digits}")
                    return digits
            return None
        except Exception as e:
            logging.error(f"Error getting 2FA code: {str(e)}")
            return None
        finally:
            if page:
                await page.close()

    async def verify_new_password(self) -> bool:
        """Verify new password by logging in and getting new cookies"""
        playwright = browser = context = page = None
        try:
            playwright, browser, context = await self.setup_browser_context()
            if not all([playwright, browser, context]):
                return False

            try:
                page = await context.new_page()
                logging.info("Starting login verification process...")
                await page.goto('https://twitter.com/i/flow/login', wait_until='networkidle')
                
                # Enter username
                logging.info("Entering username...")
                username_input = await page.wait_for_selector('input[autocomplete="username"]', timeout=30000)
                await username_input.fill(self.account_data['login'])
                await asyncio.sleep(2)
                
                await page.click('text=Next')
                await asyncio.sleep(2)
                
                # Try new password up to 3 times
                retry_count = 0
                max_retries = 3
                
                while retry_count < max_retries:
                    logging.info(f"Attempting login with new password (attempt {retry_count + 1}/{max_retries})...")
                    password_input = await page.wait_for_selector('input[name="password"]', timeout=30000)
                    await password_input.fill(self.new_password)
                    await asyncio.sleep(2)
                    
                    await page.click('text=Log in')
                    await asyncio.sleep(3)
                    
                    try:
                        # Check for error messages
                        error_selectors = [
                            '[data-testid="error-detail"]',
                            '.alert-message',
                            '.error-text',
                            '[role="alert"]'
                        ]
                        
                        error_found = False
                        for selector in error_selectors:
                            try:
                                error_element = await page.wait_for_selector(selector, timeout=2000)
                                if error_element:
                                    error_text = await error_element.text_content()
                                    if error_text:
                                        error_found = True
                                        break
                            except PlaywrightTimeoutError:
                                continue
                        
                        if not error_found:
                            # No error found, try to verify login
                            try:
                                await page.wait_for_url("https://twitter.com/home", timeout=15000)
                                logging.info("Login successful with new password")
                                return True
                            except PlaywrightTimeoutError:
                                pass
                        
                        retry_count += 1
                        if retry_count < max_retries:
                            logging.info("Retrying with new password...")
                            await asyncio.sleep(2)
                            continue
                        
                        # If we're here, new password failed 3 times
                        # Try with old password
                        logging.info("New password failed 3 times, attempting with old password...")
                        await password_input.fill(self.old_password)
                        await asyncio.sleep(2)
                        await page.click('text=Log in')
                        await asyncio.sleep(3)
                        
                        try:
                            await page.wait_for_url("https://twitter.com/home", timeout=15000)
                            logging.info("Login successful with old password")
                            # Swap passwords - make old password current and store failed new password as old
                            temp_password = self.new_password
                            self.new_password = self.old_password
                            self.old_password = temp_password
                            return True
                        except PlaywrightTimeoutError:
                            logging.error("Login failed with both new password (3 attempts) and old password")
                            return False
                            
                    except Exception as e:
                        logging.error(f"Error during login attempt: {str(e)}")
                        retry_count += 1
                        if retry_count < max_retries:
                            await asyncio.sleep(2)
                            continue
                        return False
                
                return False
                
                # Handle 2FA if needed
                if self.account_data.get('two_fa'):  # Changed from '2fa' to 'two_fa'
                    logging.info("2FA required, getting code...")
                    two_fa_input = await page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=30000)
                    if two_fa_input:
                        # Open new page for 2FA code
                        two_fa_page = await browser.new_page()
                        try:
                            url = f'https://2fa.fb.rip/{self.account_data["two_fa"]}'  # Changed from '2fa' to 'two_fa'
                            logging.info(f"Getting 2FA code from {url}")
                            
                            await two_fa_page.goto(url, wait_until='networkidle', timeout=30000)
                            await two_fa_page.wait_for_selector('#app', state='visible', timeout=30000)
                            
                            verify_code_element = await two_fa_page.wait_for_selector('#verifyCode', timeout=30000)
                            if verify_code_element:
                                code = await verify_code_element.text_content()
                                digits = ''.join(c for c in code if c.isdigit())
                                if digits and len(digits) == 6:
                                    logging.info("Successfully got 2FA code")
                                    await two_fa_input.fill(digits)
                                    await asyncio.sleep(2)
                                    
                                    await page.click('text=Next')
                                    await asyncio.sleep(3)
                                else:
                                    logging.error("Invalid 2FA code format")
                                    return False
                            else:
                                logging.error("Could not find 2FA code element")
                                return False
                        finally:
                            await two_fa_page.close()
                    else:
                        logging.error("Could not find 2FA input field")
                        return False
                
                # Verify login success
                await asyncio.sleep(5)  # Wait a bit longer for full login
                if 'home' not in page.url:
                    logging.error(f"Login verification failed. Current URL: {page.url}")
                    await page.screenshot(path=f"output/login_failed_{self.account_no}.png")
                    return False
                
                # Get new cookies
                logging.info("Getting new cookies...")
                cookies = await context.cookies()
                self.new_cookies = {
                    'ct0': next((c['value'] for c in cookies if c['name'] == 'ct0'), None),
                    'auth_token': next((c['value'] for c in cookies if c['name'] == 'auth_token'), None)
                }
                
                if not all(self.new_cookies.values()):
                    logging.error("Failed to get new cookies")
                    return False
                    
                logging.info("Successfully verified new password and got new cookies")
                password_logger.info(f"New ct0: {self.new_cookies['ct0']}")
                password_logger.info(f"New auth_token: {self.new_cookies['auth_token']}")
                return True
                
            finally:
                if page:
                    await page.close()
                
        except Exception as e:
            logging.error(f"Error in verify_new_password: {str(e)}")
            return False
        finally:
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()

    async def change_password(self) -> bool:
        """Change password using Twitter web interface"""
        playwright = browser = context = page = None
        try:
            # Initialize password change
            self.old_password = self.account_data['password']
            self.new_password = generate_secure_password()
            self.old_cookies = {
                'ct0': self.account_data['ct0'],
                'auth_token': self.account_data['auth_token']
            }
            
            # Log initial information
            logging.info(f"Starting password change for account {self.account_no}")
            password_logger.info(f"Account: {self.account_no}")
            password_logger.info(f"Old password: {self.old_password}")
            password_logger.info(f"New password: {self.new_password}")
            password_logger.info(f"Old ct0: {self.old_cookies['ct0']}")
            password_logger.info(f"Old auth_token: {self.old_cookies['auth_token']}")

            # Setup browser
            playwright, browser, context = await self.setup_browser_context()
            if not all([playwright, browser, context]):
                return False

            try:
                page = await context.new_page()
                logging.info("Navigating to password change page...")
                await page.goto('https://x.com/settings/password', timeout=60000)
                await asyncio.sleep(3)

                # Check for login redirect
                if 'login' in page.url:
                    logging.error("Not logged in, cookies might be expired")
                    await page.screenshot(path=f"output/login_redirect_{self.account_no}.png")
                    return False

                # Fill password change form
                logging.info("Filling password change form...")
                await page.fill('input[name="current_password"]', self.old_password)
                await asyncio.sleep(1)

                await page.fill('input[name="new_password"]', self.new_password)
                await asyncio.sleep(1)

                await page.fill('input[name="password_confirmation"]', self.new_password)
                await asyncio.sleep(1)

                # Click save
                logging.info("Submitting password change...")
                await page.click('span:has-text("Save")')
                await asyncio.sleep(5)

                # Verify new password
                logging.info("Starting password verification...")
                if await self.verify_new_password():
                    logging.info("Password change successful")
                    self.account_data.update({
                        'password': self.new_password,
                        'ct0': self.new_cookies['ct0'],
                        'auth_token': self.new_cookies['auth_token']
                    })
                    
                    await self.save_account_data()
                    return True
                
                logging.error("Password verification failed")
                return False

            finally:
                if page:
                    await page.close()
                
        except Exception as e:
            logging.error(f"Error in change_password: {str(e)}")
            return False
        finally:
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()

    async def save_account_data(self) -> bool:
        """Save updated account data to CSV with proper locking and backup"""
        try:
            lock = FileLock(f"{ACCOUNTS_FILE}.lock")
            with lock:
                # Read current CSV
                df = pd.read_csv(ACCOUNTS_FILE)
                
                # Create backup
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_file = f"{ACCOUNTS_FILE}.{timestamp}.bak"
                df.to_csv(backup_file, index=False)
                logging.info(f"Created backup at {backup_file}")
                
                # Update account data
                mask = df['account_no'] == self.account_no
                if not mask.any():
                    logging.error(f"Account {self.account_no} not found in CSV")
                    return False
                
                # Update values
                for col, value in self.account_data.items():
                    if col in df.columns:
                        df.loc[mask, col] = value
                
                # Save updated CSV
                df.to_csv(ACCOUNTS_FILE, index=False)
                
                logging.info(f"Saved account data for {self.account_no}")
                return True
                
        except Exception as e:
            logging.error(f"Error saving account data: {str(e)}")
            return False

async def process_account(account_data: Dict) -> Dict:
    """Process a single account with proper error handling"""
    try:
        logging.info(f"Processing account {account_data['account_no']}")
        
        manager = TwitterAccountManager(account_data)
        await manager.change_password()
        
        return manager.account_data
        
    except Exception as e:
        logging.error(f"Error processing account {account_data.get('account_no')}: {str(e)}")
        return account_data

async def process_accounts(max_concurrent: int = 4):
    """Process accounts with consistent concurrency"""
    try:
        # Read accounts from CSV
        df = pd.read_csv(ACCOUNTS_FILE)
        total_accounts = len(df)
        logging.info(f"Found {total_accounts} accounts to process")
        
        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(max_concurrent)
        
        # Process accounts in batches
        batch_size = max_concurrent
        account_batches = [df[i:i + batch_size] for i in range(0, len(df), batch_size)]
        
        for batch_num, batch in enumerate(account_batches, 1):
            logging.info(f"Processing batch {batch_num}/{len(account_batches)}")
            
            batch_tasks = []
            for _, row in batch.iterrows():
                async def process_with_semaphore(account_data: Dict):
                    async with semaphore:
                        try:
                            result = await process_account(account_data)
                            await asyncio.sleep(random.uniform(1, 3))
                            return result
                        except Exception as e:
                            logging.error(f"Error processing account {account_data.get('account_no')}: {str(e)}")
                            return account_data
                
                batch_tasks.append(process_with_semaphore(row.to_dict()))
            
            # Process batch concurrently
            batch_results = await asyncio.gather(*batch_tasks)
            
            # Add delay between batches
            if batch_num < len(account_batches):
                await asyncio.sleep(random.uniform(5, 10))
        
        logging.info("All batches completed")
        
    except Exception as e:
        logging.error(f"Error in batch processing: {str(e)}")

async def process_single_account(account_no: str):
    """Process a single account by number"""
    try:
        df = pd.read_csv(ACCOUNTS_FILE)
        account = df[df['account_no'] == account_no]
        
        if account.empty:
            logging.error(f"Account {account_no} not found")
            return
            
        account_data = account.iloc[0].to_dict()
        await process_account(account_data)
        
    except Exception as e:
        logging.error(f"Error processing single account {account_no}: {str(e)}")

def setup_folders():
    """Create necessary folders for logs and outputs"""
    folders = ['output', 'account_states']
    for folder in folders:
        os.makedirs(folder, exist_ok=True)

if __name__ == "__main__":
    # Setup folders
    setup_folders()
    
    # Setup logging for uncaught exceptions
    def handle_exception(loop, context):
        msg = context.get("exception", context["message"])
        logging.error(f"Uncaught exception: {msg}")
    
    # Get the event loop and set exception handler
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(handle_exception)
    
    try:
        if len(sys.argv) == 2:
            # Process single account
            account_no = sys.argv[1]
            logging.info(f"Starting single account process for {account_no}")
            loop.run_until_complete(process_single_account(account_no))
            logging.info(f"Completed processing account {account_no}")
        else:
            # Process all accounts
            logging.info("Starting batch processing of accounts")
            loop.run_until_complete(process_accounts())
            logging.info("Completed batch processing")
    except KeyboardInterrupt:
        logging.info("Process interrupted by user")
    except Exception as e:
        logging.error(f"Fatal error: {str(e)}")
    finally:
        loop.close()
