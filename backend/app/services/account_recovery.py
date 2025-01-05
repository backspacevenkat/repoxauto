import logging
import os
import asyncio
import imaplib
import email
import json
import socket
import time
import ssl
import traceback
from datetime import datetime, timedelta
from email.header import decode_header
import re
from urllib.parse import quote, unquote
from typing import Dict, Optional
from playwright.async_api import async_playwright, Page, TimeoutError
import httpx
from colorama import Fore, Style, init

from .captcha_solver import CaptchaSolver

# Initialize colorama
init(autoreset=True)

# Configure logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler('logs/account_recovery.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
IMAP_HOST = "imap.firstmail.ltd"
IMAP_PORT = 993
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

def format_proxy_url(proxy_info: Dict) -> str:
    """Format proxy URL with URL-encoded credentials."""
    try:
        username = quote(proxy_info['proxy_username'])
        password = quote(proxy_info['proxy_password'])
        return f"http://{username}:{password}@{proxy_info['proxy_url']}:{proxy_info['proxy_port']}"
    except Exception as e:
        logger.error(f"Error formatting proxy URL: {str(e)}")
        raise

async def check_proxy_speed(proxy_config: dict) -> float:
    """Test proxy speed with multiple endpoints."""
    try:
        proxy_url = format_proxy_url({
            'proxy_username': proxy_config['proxyLogin'],
            'proxy_password': proxy_config['proxyPassword'],
            'proxy_url': proxy_config['proxyAddress'],
            'proxy_port': proxy_config['proxyPort']
        })

        test_urls = [
            'https://api.ipify.org',
            'https://x.com/robots.txt',
            'https://client-api.arkoselabs.com'
        ]
        
        times = []
        async with httpx.AsyncClient(
            proxies={'http://': proxy_url, 'https://': proxy_url},
            timeout=15.0,
            verify=False
        ) as client:
            for url in test_urls:
                try:
                    start_time = time.time()
                    await client.get(url)
                    elapsed = time.time() - start_time
                    times.append(elapsed)
                except Exception as e:
                    logger.error(f"Speed test failed for {url}: {e}")
                    continue
                    
        if times:
            avg_time = sum(times) / len(times)
            logger.info(f"Average proxy response time: {avg_time:.2f} seconds")
            return avg_time
        return float('inf')
        
    except Exception as e:
        logger.error(f"Proxy speed test failed: {e}")
        return float('inf')

async def check_ip(proxy_config: dict) -> str:
    """Check current IP address using proxy."""
    try:
        proxy_url = format_proxy_url({
            'proxy_username': proxy_config['proxyLogin'],
            'proxy_password': proxy_config['proxyPassword'],
            'proxy_url': proxy_config['proxyAddress'],
            'proxy_port': proxy_config['proxyPort']
        })

        ip_services = [
            'https://api.ipify.org',
            'https://ifconfig.me/ip',
            'https://icanhazip.com'
        ]
        
        async with httpx.AsyncClient(
            proxies={'http://': proxy_url, 'https://': proxy_url},
            timeout=15.0,
            verify=False
        ) as client:
            for service in ip_services:
                try:
                    response = await client.get(service)
                    if response.status_code == 200:
                        ip_address = response.text.strip()
                        logger.info(f"Current IP Address: {ip_address}")
                        return ip_address
                except Exception as e:
                    logger.error(f"Error with {service}: {e}")
                    continue
                    
        return "Unknown (All IP services failed)"
        
    except Exception as e:
        logger.error(f"Failed to check IP: {e}")
        return "Unknown"

async def get_verification_code(account: dict) -> Optional[str]:
    """Get email verification code with enhanced error handling."""
    imap = None
    try:
        logger.info(f"Connecting to IMAP server {IMAP_HOST}:{IMAP_PORT}")
        
        # Connect to IMAP server
        imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        
        # Login to email account
        try:
            imap.login(account['email'], account['email_password'])
            logger.info("Successfully logged into IMAP")
        except Exception as e:
            logger.error(f"IMAP login failed: {e}")
            return None

        # Select inbox
        imap.select('INBOX')
        
        # Search ALL messages without date filter
        search_criteria = 'ALL'
        
        for attempt in range(12):  # Try for 1 minute
            try:
                # Search for messages
                _, message_numbers = imap.search(None, search_criteria)
                message_list = message_numbers[0].split()
                logger.info(f"Found {len(message_list)} total emails")
                
                # Store all found codes with their dates
                codes_with_dates = []
                
                # Check messages from newest to oldest
                for num in reversed(message_list[-50:]):  # Look at last 50 emails
                    try:
                        # Fetch message
                        _, msg_data = imap.fetch(num, '(RFC822)')
                        email_body = msg_data[0][1]
                        message = email.message_from_bytes(email_body)
                        
                        # Get sender and date
                        sender = message.get('from', '').lower()
                        date_str = message.get('date', '')
                        
                        # Parse email date
                        try:
                            email_date = email.utils.parsedate_to_datetime(date_str)
                        except:
                            email_date = datetime.now()
                        
                        logger.info(f"Checking email from {sender} sent {date_str}")
                        
                        # Check if it's from Twitter/X or our email providers
                        email_domains = [
                            '@x.com', '@twitter.com',
                            '@firstmail.ltd', '@dfirstmail.com', '@sfirstmail.com',
                            '@maillv.com', '@maillsk.com', '@fmaild.com'
                        ]
                        
                        if any(domain in sender for domain in email_domains):
                            # Get subject
                            subject = decode_header(message.get('subject', ''))[0][0]
                            if isinstance(subject, bytes):
                                subject = subject.decode()
                            
                            logger.info(f"Found relevant email with subject: {subject}")
                            
                            # Check subject patterns
                            subject_patterns = [
                                r'(\d{6})[^\d]*verification code',
                                r'verification code[^\d]*(\d{6})',
                                r'(\d{6}) is your X code',
                                r'(\d{6}) is your Twitter code',
                                r'Verification code: (\d{6})',
                                r'Code: (\d{6})',
                                r'Your code is (\d{6})',
                                r'Your verification code is (\d{6})',
                                r'Use this code to verify: (\d{6})',
                                r'(\d{6})'  # Last resort - any 6 digits
                            ]
                            
                            for pattern in subject_patterns:
                                match = re.search(pattern, subject, re.IGNORECASE)
                                if match:
                                    code = match.group(1)
                                    logger.info(f"Found code in subject: {code}")
                                    codes_with_dates.append((code, email_date))
                                    break
                            
                            # If not found in subject, check message body
                            if not codes_with_dates:
                                body = ""
                                if message.is_multipart():
                                    for part in message.walk():
                                        if part.get_content_type() == "text/plain":
                                            try:
                                                body = part.get_payload(decode=True).decode()
                                            except:
                                                body = part.get_payload(decode=True).decode('utf-8', 'ignore')
                                            break
                                else:
                                    try:
                                        body = message.get_payload(decode=True).decode()
                                    except:
                                        body = message.get_payload(decode=True).decode('utf-8', 'ignore')
                                
                                logger.info("Checking email body for verification code")
                                
                                body_patterns = [
                                    r'verification code[^\d]*(\d{6})',
                                    r'code to continue[^\d]*(\d{6})',
                                    r'code is[^\d]*(\d{6})',
                                    r'here\'s your code[^\d]*(\d{6})',
                                    r'(\d{6})\s+is your[^$]+verification code',
                                    r'Your code is[^\d]*(\d{6})',
                                    r'Use this code[^\d]*(\d{6})',
                                    r'Enter this code[^\d]*(\d{6})',
                                    r'confirmation code[^\d]*(\d{6})',
                                    r'security code[^\d]*(\d{6})',
                                    r'(\d{6})'  # Last resort - any 6 digits
                                ]
                                
                                for pattern in body_patterns:
                                    match = re.search(pattern, body, re.IGNORECASE)
                                    if match:
                                        code = match.group(1)
                                        logger.info(f"Found code in body: {code}")
                                        codes_with_dates.append((code, email_date))
                                        break
                    
                    except Exception as e:
                        logger.error(f"Error processing message {num}: {e}")
                        continue
                
                # If we found any codes, return the most recent one
                if codes_with_dates:
                    # Sort by date, newest first
                    codes_with_dates.sort(key=lambda x: x[1], reverse=True)
                    latest_code = codes_with_dates[0][0]
                    logger.info(f"Using latest verification code: {latest_code}")
                    return latest_code
                
                logger.info(f"No verification code found, attempt {attempt + 1}/12")
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Error searching messages: {e}")
                await asyncio.sleep(5)
                continue

        logger.error("No verification code found after all attempts")
        return None

    except Exception as e:
        logger.error(f"Error getting verification code: {e}")
        return None

    finally:
        if imap:
            try:
                imap.close()
                imap.logout()
            except:
                pass

async def is_on_home_page(page: Page) -> bool:
    """Check if currently on Twitter home page."""
    try:
        # First check URL (fastest)
        if '/home' not in page.url:
            return False
            
        # Check for essential home page elements using single query
        indicators = await page.evaluate('''
            () => {
                const selectors = [
                    '[data-testid="primaryColumn"]',
                    '[data-testid="SideNav_NewTweet_Button"]',
                    '[data-testid="AppTabBar_Home_Link"]'
                ];
                return selectors.filter(s => document.querySelector(s)).length;
            }
        ''')
        
        is_home = indicators >= 2
        if is_home:
            logger.info("Confirmed home page with URL and indicators")
        return is_home

    except Exception as e:
        logger.error(f"Error checking home page: {e}")
        return False

async def is_email_verification_page(page: Page) -> bool:
    """Check if on email verification page."""
    try:
        verification_indicators = [
            'text="We sent you a code"',
            'text="Enter Verification Code"',
            'text="Check"',
            'text="for your verification code"',
            'text="Didn\'t receive an email?"',
            'input[name="verification_code"]',
            'div:has-text("Enter the code")',
            'input[autocomplete="one-time-code"]',
            '[data-testid="ocfEnterTextTextInput"]'
        ]
        
        for indicator in verification_indicators:
            try:
                element = await page.wait_for_selector(indicator, timeout=3000)
                if element:
                    logger.info(f"Found verification indicator: {indicator}")
                    return True
            except Exception:
                continue
        
        # Also check URL for verification indicators
        current_url = page.url
        if any(x in current_url.lower() for x in ['verify', 'verification', 'confirm']):
            logger.info(f"Found verification indicator in URL: {current_url}")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error checking verification page: {e}")
        return False

async def handle_email_verification(page: Page, account: dict) -> bool:
    """Handle email verification flow."""
    try:
        logger.info("Starting email verification process...")

        # First make sure we click the Send Email button if it exists
        send_email_button = await page.query_selector(
            'input[type="submit"][value="Send email"][class="Button EdgeButton--primary EdgeButton"]'
        )
        if send_email_button:
            logger.info("Found Send Email button, clicking it")
            await send_email_button.click()
            await asyncio.sleep(2)

        # Now wait for the verification input to appear
        verify_code_input = await page.wait_for_selector(
            'input[name="token"][class*="Form-textbox"]',
            timeout=10000
        )
        
        if not verify_code_input:
            logger.error("Could not find verification code input after clicking Send Email")
            return False

        # Get the verification code
        verification_code = await get_verification_code(account)
        if not verification_code:
            logger.error("Failed to get verification code")
            return False
            
        logger.info(f"Entering verification code: {verification_code}")
        await verify_code_input.fill("")
        await verify_code_input.type(verification_code, delay=10)
        
        # Click verify button
        verify_button = await page.query_selector(
            'input[type="submit"][value="Verify"][class="Button EdgeButton--primary EdgeButton"]'
        )
        if verify_button:
            logger.info("Clicking Verify button")
            await verify_button.click()
            await asyncio.sleep(2)
            
            # Wait for success - either home page or Continue to X
            for _ in range(5):  # 10 seconds total
                if await is_on_home_page(page):
                    logger.info("Successfully reached home page after verification")
                    return True

                continue_button = await page.query_selector(
                    'input[type="submit"][value="Continue to X"][class="Button EdgeButton--primary EdgeButton"]'
                )
                if continue_button:
                    logger.info("Found Continue to X button after verification")
                    await continue_button.click()
                    await asyncio.sleep(2)
                    if await is_on_home_page(page):
                        logger.info("Successfully reached home page")
                        return True
                await asyncio.sleep(2)

        logger.error("Could not complete verification process")
        return False

    except Exception as e:
        logger.error(f"Error in email verification: {e}")
        return False

async def handle_unexpected_popups(page: Page):
    """Handle unexpected popups and overlays."""
    try:
        popup_selectors = [
            '.modal-close-button',
            'button:has-text("Close")',
            'button:has-text("Not now")',
            'button:has-text("Skip")',
            '[aria-label="Close"]',
            'button:has-text("Maybe later")',
            'button:has-text("Cancel")'
        ]
        
        for selector in popup_selectors:
            try:
                popup = await page.wait_for_selector(selector, timeout=3000)
                if popup:
                    await popup.click()
                    logger.info(f"Closed popup with selector: {selector}")
                    await asyncio.sleep(1)
            except Exception:
                continue

    except Exception as e:
        logger.error(f"Error handling popups: {e}")

async def recover_account(account: dict, proxy_config: dict) -> str:
    """Main account recovery function."""
    try:
        overall_retry_count = 3  # Number of complete recovery attempts
        
        for attempt in range(overall_retry_count):
            try:
                logger.info(f"Starting recovery attempt {attempt + 1}/{overall_retry_count} for account {account['account_no']}")

                # Test proxy speed and connectivity
                proxy_speed = await check_proxy_speed(proxy_config)
                if proxy_speed == float('inf'):
                    logger.error("Proxy test failed")
                    return "NOT RECOVERED (Bad Proxy)"

                # Verify IP address
                ip_address = await check_ip(proxy_config)
                logger.info(f"Using proxy IP: {ip_address}")
                if ip_address == "Unknown":
                    logger.error("Failed to verify proxy connection")
                    return "NOT RECOVERED (Bad Proxy)"

                async with async_playwright() as p:
                    try:
                        # Enhanced browser configuration
                        browser_args = [
                            '--disable-blink-features=AutomationControlled',
                            '--disable-features=IsolateOrigins,site-per-process',
                            '--disable-web-security',
                            '--disable-site-isolation-trials',
                            '--no-sandbox',
                            '--window-size=1920,1080'
                        ]

                        # Format proxy URL with encoded credentials
                        proxy_url = format_proxy_url({
                            'proxy_username': proxy_config['proxyLogin'],
                            'proxy_password': proxy_config['proxyPassword'],
                            'proxy_url': proxy_config['proxyAddress'],
                            'proxy_port': proxy_config['proxyPort']
                        })

                        # Launch browser
                        browser = await p.chromium.launch(
                            headless=True,
                            proxy={
                                "server": proxy_url,
                                "username": proxy_config['proxyLogin'],
                                "password": proxy_config['proxyPassword']
                            },
                            args=browser_args,
                            devtools=True
                        )

                        # Enhanced context settings
                        context = await browser.new_context(
                            user_agent=account.get('user_agent', USER_AGENT),
                            viewport={'width': 1920, 'height': 1080},
                            ignore_https_errors=True,
                            bypass_csp=True,
                            permissions=['clipboard-read', 'clipboard-write']
                        )

                        # Set up cookies
                        cookies = [
                            {
                                'name': 'ct0',
                                'value': account['ct0'],
                                'domain': '.twitter.com',
                                'path': '/',
                                'secure': True,
                                'httpOnly': True
                            },
                            {
                                'name': 'auth_token',
                                'value': account['auth_token'],
                                'domain': '.twitter.com',
                                'path': '/',
                                'secure': True,
                                'httpOnly': True
                            }
                        ]
                        await context.add_cookies(cookies)

                        page = await context.new_page()
                        page.set_default_navigation_timeout(60000)
                        page.set_default_timeout(30000)

                        # Quick home check before navigation
                        await page.goto('https://x.com/home')
                        if await is_on_home_page(page):
                            logger.info("Already on home page")
                            return "RECOVERED (Already Active)"

                        # Navigate to access page
                        await page.goto('https://x.com/account/access')
                        await asyncio.sleep(2)

                        # Initialize CaptchaSolver
                        captcha_solver = CaptchaSolver(proxy_config)
                        await captcha_solver.setup_page_handlers(page)

                        # State handling loop
                        state_handle_attempts = 5
                        for state_attempt in range(state_handle_attempts):
                            # Handle email verification if needed
                            if await is_email_verification_page(page):
                                logger.info("Found email verification page")
                                if await handle_email_verification(page, account):
                                    if await is_on_home_page(page):
                                        return "RECOVERED (After Email Verification)"
                                continue

                            # Handle captcha if present
                            if await captcha_solver.solve_captcha_challenge():
                                if await is_on_home_page(page):
                                    return "RECOVERED (After Captcha)"
                                continue

                            # Handle unexpected popups
                            await handle_unexpected_popups(page)

                            # Check if we reached home page
                            if await is_on_home_page(page):
                                return "RECOVERED (Success)"

                            await asyncio.sleep(2)

                        logger.error(f"Recovery attempt {attempt + 1} failed to reach home page")
                        if attempt < overall_retry_count - 1:
                            logger.info("Retrying complete recovery process")
                            await asyncio.sleep(5)
                            continue

                    except Exception as e:
                        logger.error(f"Error in recovery attempt {attempt + 1}: {e}")
                        if attempt < overall_retry_count - 1:
                            logger.info("Retrying after error")
                            await asyncio.sleep(5)
                            continue
                        else:
                            return f"NOT RECOVERED (Error: {str(e)[:100]})"

                    finally:
                        try:
                            if 'browser' in locals():
                                await browser.close()
                                logger.info("Browser closed successfully")
                        except Exception as e:
                            logger.error(f"Error closing browser: {e}")

            except Exception as e:
                logger.error(f"Error in recovery attempt {attempt}: {e}")
                if attempt < overall_retry_count - 1:
                    await asyncio.sleep(5)
                    continue
                return f"NOT RECOVERED (Error: {str(e)[:100]})"

        logger.error("All recovery attempts exhausted")
        return "NOT RECOVERED (Max Attempts Reached)"

    except Exception as e:
        logger.error(f"Fatal error in account recovery: {e}")
        logger.error(traceback.format_exc())
        return f"NOT RECOVERED (Fatal Error: {str(e)[:100]})"
