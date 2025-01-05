import asyncio
import pandas as pd
from playwright.async_api import async_playwright, Page, TimeoutError, ElementHandle, Response
import logging
import os
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
import re
from colorama import Fore, Style, init
import urllib.parse
import sys
import traceback
from twocaptcha import TwoCaptcha
import httpx
import json
import socket
import time
import ssl
from urllib.parse import quote
from urllib.parse import parse_qs, urlparse, unquote
from typing import Dict, List, Optional
from twikit import Client


# Initialize colorama
init(autoreset=True)

# Configure logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler('logs/unlock_accounts_detailed.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
IMAP_HOST = "imap.firstmail.ltd"
IMAP_PORT = 993
TWO_CAPTCHA_API_KEY = '4a5a819b86f4644d2fc770f53bdc40bc'
PUBLIC_KEY = "0152B4EB-D2DC-460A-89A1-629838B529C9"
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

def print_colored(text, color):
    """Print colored text using colorama."""
    print(f"{color}{text}{Style.RESET_ALL}")

def get_proxy_config(account: dict) -> dict:
    """Get proxy configuration from account data."""
    try:
        port = int(float(account['proxy_port']))
        proxy_address = account['proxy_url']
        proxy_port = port
        logger.info(f"Constructed Proxy Address: {proxy_address}:{proxy_port}")
        return {
            'proxytype': account.get('proxytype', 'http').lower(),  # Default to http if not specified
            'proxyAddress': proxy_address,
            'proxyPort': proxy_port,
            'proxyLogin': account['proxy_username'],
            'proxyPassword': account['proxy_password']
        }
    except ValueError as e:
        logger.error(f"Invalid proxy port for account {account['account_no']}: {e}")
        return None
    except KeyError as e:
        logger.error(f"Missing proxy configuration key for account {account['account_no']}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error getting proxy config for account {account['account_no']}: {e}")
        return None

async def is_on_home_page(page: Page) -> bool:
    """Enhanced home page detection with multiple indicators."""
    try:
        current_url = page.url
        parsed_url = urlparse(current_url)
        logger.info(f"Current URL: {current_url}")
        
        # Check URL path
        is_home = parsed_url.path == '/home'
        if not is_home:
            return False
            
        # Verify home page elements
        home_indicators = [
            '[data-testid="primaryColumn"]',
            '[data-testid="sidebarColumn"]',
            '[data-testid="AppTabBar_Home_Link"]',
            'div[aria-label="Home timeline"]'
        ]
        
        # Check for presence of home page elements
        found_elements = 0
        for indicator in home_indicators:
            try:
                element = await page.wait_for_selector(indicator, timeout=3000)
                if element:
                    found_elements += 1
            except Exception:
                continue
                
        # Consider it home page if we find at least 2 indicators
        is_home_content = found_elements >= 2
        logger.info(f"Home page detection - URL: {is_home}, Content indicators found: {found_elements}")
        
        return is_home_content
        
    except Exception as e:
        logger.error(f"Error checking home page: {e}")
        return False

async def is_email_verification_page(page: Page) -> bool:
    """Enhanced email verification page detection with more specific indicators."""
    try:
        verification_indicators = [
            'text="We sent your verification code"',
            'text="Enter Verification Code"',
            'text="Check"',
            'text="for your verification code"',
            'text="Didn\'t receive an email?"',
            'input[name="verification_code"]',
            'div:has-text("Enter the code")',
            'input[autocomplete="one-time-code"]',
            '[data-testid="ocfEnterTextTextInput"]',
            'text="Check your email"',
            'text="Enter it below to verify"',
            'text="Enter verification code"',
            'form[data-testid="LoginForm"]',
            'div[data-testid="LoginForm_Login_Button"]',
            'div:has-text("We sent your verification code")',
            'div:has-text("Check")',
            'div:has-text("for your verification code")',
            'div:has-text("Enter Verification Code")'
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
        logger.error(f"Error checking email verification page: {e}")
        return False

async def is_authenticate_page(page: Page) -> bool:
    """Enhanced authentication page detection."""
    try:
        auth_indicators = [
            'iframe[src*="arkoselabs"]',
            'iframe#arkose_iframe',
            'button[data-theme="home.verifyButton"]',
            'button:has-text("Authenticate")',
            '.challenge-container'
        ]
        
        for indicator in auth_indicators:
            try:
                element = await page.wait_for_selector(indicator, timeout=3000)
                if element:
                    logger.info(f"Found authentication indicator: {indicator}")
                    return True
            except Exception:
                continue
                
        return False
        
    except Exception as e:
        logger.error(f"Error checking authenticate page: {e}")
        return False

async def navigate_with_retry(page: Page, url: str, max_attempts: int = 3) -> bool:
    """Enhanced navigation with better error handling."""
    for attempt in range(max_attempts):
        try:
            timeout = 60000 * (attempt + 1)  # Increasing timeouts
            logger.info(f"Navigation attempt {attempt + 1} to {url} with timeout {timeout}ms")

            response = await page.goto(
                url,
                timeout=timeout,
                wait_until='domcontentloaded'
            )
            
            if response and response.ok:
                logger.info(f"Successfully navigated to {url}")
                
                # Additional verification of page load
                try:
                    await page.wait_for_load_state('networkidle', timeout=10000)
                except Exception:
                    logger.info("Network not fully idle, but page loaded")
                    
                return True
                
            elif response:
                status = response.status
                logger.warning(f"Navigation completed with status {status}")
                if status < 400:  # Accept any non-error status
                    return True
                    
        except TimeoutError:
            logger.warning(f"Timeout on attempt {attempt + 1}")
        except Exception as e:
            logger.error(f"Navigation error: {e}")
            
        if attempt < max_attempts - 1:
            await asyncio.sleep(5)
            continue
            
    return False

async def check_ip(proxy_config: dict) -> str:
    """Enhanced IP checking with better error handling."""
    if not proxy_config:
        return "Unknown (Invalid proxy configuration)"

    try:
        username = urllib.parse.quote(proxy_config['proxyLogin'], safe='')
        password = urllib.parse.quote(proxy_config['proxyPassword'], safe='')
        proxy_url = f"http://{username}:{password}@{proxy_config['proxyAddress']}:{proxy_config['proxyPort']}"

        # Try multiple IP check services
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

async def check_proxy_speed(proxy_config: dict) -> float:
    """Enhanced proxy speed check with multiple test URLs."""
    try:
        # username = urllib.parse.quote(proxy_config['proxyLogin'], safe='')
        # password = urllib.parse.quote(proxy_config['proxyPassword'], safe='')
        # proxy_url = f"http://{username}:{password}@{proxy_config['proxyAddress']}:{proxy_config['proxyPort']}"

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

async def verify_page_state(page: Page) -> dict:
    """Verify current page state with comprehensive checks."""
    try:
        state = await page.evaluate('''
            () => {
                return {
                    url: window.location.href,
                    readyState: document.readyState,
                    hasArkose: !!document.querySelector('iframe[src*="arkoselabs"]'),
                    hasError: !!document.querySelector('.error-container'),
                    hasLoading: !!document.querySelector('.circle-loader-container'),
                    hasAuthButton: !!document.querySelector('button[data-theme="home.verifyButton"]'),
                    hasVerification: !!document.querySelector('input[name="verification_code"]'),
                    visibleButtons: Array.from(document.querySelectorAll('button')).map(b => ({
                        text: b.textContent,
                        visible: window.getComputedStyle(b).display !== 'none'
                    }))
                }
            }
        ''')
        
        return state
    except Exception as e:
        logger.error(f"Error verifying page state: {e}")
        return {}

async def check_continue_button(page: Page) -> bool:
    """Check for and click Continue to X button."""
    try:
        continue_button_selectors = [
            'input[type="submit"][class="Button EdgeButton EdgeButton--primary"][value="Continue to X"]',
            'input[type="submit"][value="Continue to X"]',
            'button:has-text("Continue to X")',
            'div[role="button"]:has-text("Continue to X")',
            '.Button.EdgeButton--primary.EdgeButton:has-text("Continue to X")',
            '[data-testid="confirmationSheetConfirm"]:has-text("Continue")'
        ]

        for selector in continue_button_selectors:
            try:
                button = await page.wait_for_selector(selector, timeout=3000)
                if button:
                    logger.info(f"Found Continue to X button with selector: {selector}")
                    await button.click()
                    logger.info("Clicked Continue to X button")
                    await asyncio.sleep(2)  # Wait for navigation
                    return True
            except Exception:
                continue

        return False
    except Exception as e:
        logger.error(f"Error checking continue button: {e}")
        return False

async def handle_email_verification(page: Page, account: dict) -> bool:
    """
    Fixed email verification handler that properly handles the flow:
    1. Click Send email button
    2. Wait for verification code
    3. Enter code and verify
    4. Handle Continue to X
    """
    try:
        logger.info("Starting email verification process...")

        # First make sure we click the Send Email button if it exists
        send_email_button = await page.query_selector(
            'input[type="submit"][value="Send email"][class="Button EdgeButton--primary EdgeButton"]'
        )
        if send_email_button:
            logger.info("Found Send Email button, clicking it")
            await send_email_button.click()
            await asyncio.sleep(2)  # Wait for email to be sent

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


async def get_verification_code(account: dict) -> str:
    """Enhanced verification code retrieval using IMAP with latest code."""
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
                
                # Get message numbers as a list
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
                            email_date = datetime.now()  # Default to now if parsing fails
                        
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
                                logger.info(f"Email body preview: {body[:200]}...")
                                
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
                    imap.close()
                    imap.logout()
                    return latest_code
                
                logger.info(f"No verification code found, attempt {attempt + 1}/12")
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Error searching messages: {e}")
                await asyncio.sleep(5)
                continue
        
        # Cleanup
        imap.close()
        imap.logout()
        return None

    except Exception as e:
        logger.error(f"Error getting verification code: {e}")
        if 'imap' in locals():
            try:
                imap.close()
                imap.logout()
            except:
                pass
        return None

async def handle_authentication(page: Page, proxy_config: dict) -> bool:
    """Enhanced authentication handler integrating with CaptchaSolver."""
    try:
        logger.info("Starting enhanced authentication process...")
        
        # Initialize CaptchaSolver
        captcha_handler = CaptchaSolver(proxy_config)
        #captcha_handler = CaptchaSolver(proxy_config, TWO_CAPTCHA_API_KEY)
        await captcha_handler.setup_page_handlers(page)
        
        # Wait for page stabilization
        await asyncio.sleep(2)
        
        # Verify initial page state
        page_state = await verify_page_state(page)
        logger.info(f"Initial page state: {page_state}")
        
        if page_state.get('hasError'):
            logger.error("Error state detected on page")
            return False

        # Handle loading animation with retry
        try:
            await page.wait_for_selector('.circle-loader-container', state='hidden', timeout=30000)
            logger.info("Loading animation disappeared")
        except TimeoutError:
            logger.warning("Loading animation persisted, but continuing...")

        # Click authenticate button if present
        authenticate_button_selectors = [
            'button[data-theme="home.verifyButton"]',
            'button:has-text("Authenticate")',
            'button.authenticate-button',
            'button#authenticate',
            'input[type="submit"][value="Authenticate"]'
        ]

        # Try to find and click authenticate button
        auth_button_clicked = False
        for selector in authenticate_button_selectors:
            try:
                button = await page.wait_for_selector(selector, timeout=3000, state='visible')
                if button:
                    await asyncio.sleep(1)  # Brief pause before clicking
                    await button.click()
                    logger.info(f"Clicked authenticate button: {selector}")
                    auth_button_clicked = True
                    await asyncio.sleep(3)  # Wait for click effect
                    break
            except Exception as e:
                logger.debug(f"Failed to find/click button {selector}: {e}")
                continue

        if not auth_button_clicked:
            logger.info("No authenticate button found, checking if already in authentication flow")
            
            # Check if already in authentication flow
            if await is_authenticate_page(page):
                logger.info("Already on authentication page")
            else:
                logger.error("Could not find authenticate button or authentication page")
                return False

        # Solve captcha challenge
        captcha_success = await captcha_handler.solve_captcha_challenge()
        if not captcha_success:
            logger.error("Failed to solve captcha challenge")
            return False

        logger.info("Captcha challenge completed, verifying success...")

        # Enhanced success verification
        success = False
        for attempt in range(3):  # 60 seconds total
            try:
                # Check for home page
                if await is_on_home_page(page):
                    logger.info("Successfully reached home page")
                    success = True
                    break

                # Check for verification flow
                if await is_email_verification_page(page):
                    logger.info("Reached email verification page")
                    success = True
                    break

                # Check if challenge is gone
                if not await is_authenticate_page(page):
                    logger.info("Authentication challenge no longer present")
                    await asyncio.sleep(3)  # Wait for potential redirect
                    if await is_on_home_page(page):
                        success = True
                        break

                await asyncio.sleep(3)
                logger.info(f"Success verification attempt {attempt + 1}/12")

            except Exception as e:
                logger.error(f"Error in success verification: {e}")
                await asyncio.sleep(3)

        if not success:
            logger.error("Could not verify successful authentication")
            return False

        return True

    except Exception as e:
        logger.error(f"Error in authentication handler: {e}")
        logger.error(traceback.format_exc())
        return False


async def handle_account_access_page(page: Page, account: dict, proxy_config: dict) -> bool:
    """
    Enhanced account access handler with faster state detection.
    """
    try:
        # First check if already on home page
        if await is_on_home_page(page):
            logger.info("Already on home page")
            return True
            
        # Get all buttons on the page at once
        buttons = await page.evaluate('''
            () => {
                const buttons = Array.from(document.querySelectorAll('input[type="submit"], button'));
                return buttons.map(b => ({
                    type: b.tagName.toLowerCase(),
                    value: b.value || '',
                    text: b.textContent || '',
                    classes: b.className,
                    isVisible: window.getComputedStyle(b).display !== 'none'
                }));
            }
        ''')
        
        logger.info(f"Found {len(buttons)} buttons on page")
        
        # Determine current state based on visible buttons
        current_state = None
        button_to_click = None
        
        for button in buttons:
            if not button['isVisible']:
                continue
                
            if button['value'] == 'Start' and 'EdgeButton--primary' in button['classes']:
                current_state = 'start'
                button_selector = 'input[type="submit"][value="Start"][class*="EdgeButton--primary"]'
                break
                
            elif button['value'] == 'Send email' and 'EdgeButton--primary' in button['classes']:
                current_state = 'send_email'
                button_selector = 'input[type="submit"][value="Send email"][class*="EdgeButton--primary"]'
                break
                
            elif button['value'] == 'Continue to X' and 'EdgeButton--primary' in button['classes']:
                current_state = 'continue'
                button_selector = 'input[type="submit"][value="Continue to X"][class*="EdgeButton--primary"]'
                break

        # Check for verification input field
        verify_input = await page.query_selector('input[name="token"][class*="Form-textbox"]')
        if verify_input:
            current_state = 'verify'
            
        # Check for authentication/captcha
        if await is_authenticate_page(page):
            current_state = 'authenticate'

        logger.info(f"Current page state: {current_state}")

        # Handle each state
        if current_state == 'start':
            logger.info("Found Start button")
            await page.click(button_selector)
            await asyncio.sleep(1)
            return True
            
        elif current_state == 'send_email':
            logger.info("Found Send email button")
            await page.click(button_selector)
            await asyncio.sleep(1)
            
            # Wait for code input state
            verify_code_input = await page.wait_for_selector(
                'input[name="token"][class*="Form-textbox"]',
                timeout=10000
            )
            
            if verify_code_input:
                verification_code = await get_verification_code(account)
                if not verification_code:
                    return False
                await verify_code_input.fill("")
                await verify_code_input.type(verification_code, delay=10)
                
                # Click verify button
                await page.click('input[type="submit"][value="Verify"]')
                await asyncio.sleep(2)
            return True
            
        elif current_state == 'verify':
            logger.info("Found verification input")
            verification_code = await get_verification_code(account)
            if not verification_code:
                return False
            
            await page.fill('input[name="token"][class*="Form-textbox"]', "")
            await page.type('input[name="token"][class*="Form-textbox"]', verification_code, delay=10)
            await page.click('input[type="submit"][value="Verify"]')
            await asyncio.sleep(2)
            return True
            
        elif current_state == 'authenticate':
            logger.info("Found authenticate challenge")
            return await handle_authentication(page, proxy_config)
            
        elif current_state == 'continue':
            logger.info("Found Continue to X button")
            await page.click(button_selector)
            await asyncio.sleep(2)
            return await is_on_home_page(page)
            
        logger.error("No recognizable state found on page")
        return False

    except Exception as e:
        logger.error(f"Error in account access handler: {e}")
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

async def handle_continue_to_x(page: Page):
    """Enhanced handler for 'Continue to X' button."""
    try:
        logger.info("Looking for 'Continue to X' button...")
        
        # Multiple button selectors
        button_selectors = [
            'input[type="submit"][value="Continue to X"][class="Button EdgeButton--primary EdgeButton"]',
            'input.Button.EdgeButton--primary.EdgeButton[type="submit"][value="Continue to X"]',
            'button:has-text("Continue to X")',
            'button:text("Continue to X")',
            'button.continue-to-x',
            'button.authenticate-button',
            'button#continue',
            'button.primary'
        ]
        
        # Try each selector
        continue_button = None
        for selector in button_selectors:
            try:
                continue_button = await page.wait_for_selector(selector, timeout=5000, state='visible')
                if continue_button:
                    break
            except Exception:
                continue

        if continue_button:
            logger.info("Found 'Continue to X' button. Clicking it.")
            await continue_button.click()
            logger.info("Clicked 'Continue to X' button")
            
            # Check for successful navigation
            for attempt in range(3):  # 30 seconds total
                if await is_on_home_page(page):
                    logger.info("Successfully reached home page")
                    return "RECOVERED"
                await asyncio.sleep(3)
            
            logger.info(f"Did not reach home page after clicking button. Current URL: {page.url}")
            
        return None

    except Exception as e:
        logger.error(f"Error handling 'Continue to X' button: {e}")
        return None

def print_colored(text, color):
    """Print colored text using colorama."""
    print(f"{color}{text}{Style.RESET_ALL}")

async def is_verification_page(page: Page) -> bool:
    """Check if on verification page."""
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
            '[data-testid="ocfEnterTextTextInput"]',
            'text="Check your email"',
            'text="Enter it below to verify"',
            'text="Enter verification code"',
            'form[data-testid="LoginForm"]',
            'div[data-testid="LoginForm_Login_Button"]',
            'div:has-text("We sent your verification code")',
            'div:has-text("Check")',
            'div:has-text("for your verification code")',
            'div:has-text("Enter Verification Code")'
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

def format_proxy_url(proxy_info: Dict) -> str:
    """Format proxy URL with URL-encoded credentials."""
    try:
        # URL encode username and password
        username = quote(proxy_info['proxy_username'])
        password = quote(proxy_info['proxy_password'])
        
        # Format proxy URL with credentials
        return f"http://{username}:{password}@{proxy_info['proxy_url']}:{proxy_info['proxy_port']}"
    except Exception as e:
        logger.error(f"Error formatting proxy URL: {str(e)}")
        raise


async def check_account_status(account: dict, proxy_config: dict) -> str:
    """Check Twitter account status using GraphQL API."""
    try:
        # Format proxy URL using existing function
        proxy_url = format_proxy_url({
            'proxy_username': proxy_config['proxyLogin'],
            'proxy_password': proxy_config['proxyPassword'],
            'proxy_url': proxy_config['proxyAddress'],
            'proxy_port': proxy_config['proxyPort']
        })

        logger.info(f"Checking status for account {account['account_no']}")
        logger.info(f"Using proxy: {proxy_config['proxyAddress']}:{proxy_config['proxyPort']}")

        endpoint = "https://twitter.com/i/api/graphql/NimuplG1OB7Fd2btCLdBOw/UserByScreenName"
        
        variables = {
            "screen_name": account['login'],
            "withSafetyModeUserFields": True
        }

        features = {
            "hidden_profile_likes_enabled": True,
            "hidden_profile_subscriptions_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "subscriptions_verification_info_is_identity_verified_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "highlights_tweets_tab_ui_enabled": True,
            "responsive_web_twitter_article_notes_tab_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True
        }

        headers = {
            "User-Agent": account.get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'),
            "Authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs=1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA",
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-client-language": "en",
            "x-twitter-active-user": "yes",
            "content-type": "application/json",
            "x-csrf-token": account['ct0'],
            "cookie": f"auth_token={account['auth_token']}; ct0={account['ct0']}",
            "Referer": "https://twitter.com/",
            "x-client-transaction-id": f"client-transaction-{int(time.time() * 1000)}"
        }

        async with httpx.AsyncClient(
            proxies={
                'http://': proxy_url,
                'https://': proxy_url
            },
            verify=False,
            follow_redirects=True,
            timeout=30.0
        ) as client:
            response = await client.get(
                endpoint,
                headers=headers,
                params={
                    'variables': json.dumps(variables),
                    'features': json.dumps(features)
                }
            )

            if response.status_code != 200:
                logger.error(f"HTTP {response.status_code} response: {response.text}")
                try:
                    error_data = response.json()
                    error = error_data.get('errors', [{}])[0]
                    error_code = error.get('code')
                    
                    if error_code == 63:
                        return "RECOVERED (Account Status: suspended)"
                    elif error_code == 50:
                        return "RECOVERED (Account Status: not_found)"
                    elif error_code == 215:
                        return "RECOVERED (Account Status: invalid_auth)"
                    elif error_code == 88:
                        return "RECOVERED (Account Status: rate_limited)"
                    else:
                        return f"RECOVERED (Account Status: error_{error_code})"
                except:
                    return f"RECOVERED (Account Status: error_{response.status_code})"

            response_data = response.json()
            if 'data' in response_data and 'user' in response_data['data']:
                user_data = response_data['data']['user']['result']
                if user_data.get('__typename') == 'UserUnavailable':
                    return "RECOVERED (Account Status: unavailable)"
                else:
                    legacy_data = user_data.get('legacy', {})
                    if legacy_data.get('verified_type') == 'Developer':
                        return "RECOVERED (Account Status: active, Developer: Yes)"
                    return "RECOVERED (Account Status: active)"
            else:
                return "RECOVERED (Account Status: not_found)"

    except httpx.ProxyError:
        logger.error("Proxy connection error")
        return "RECOVERED (Account Status: proxy_error)"
    except httpx.TimeoutException:
        logger.error("Request timed out")
        return "RECOVERED (Account Status: timeout)"
    except Exception as e:
        error_msg = str(e).lower()
        logger.error(f"Error checking account status: {error_msg}")
        
        if "suspended" in error_msg:
            status = "suspended"
        elif "locked" in error_msg:
            status = "locked"
        elif "unauthorized" in error_msg:
            status = "invalid_auth"
        elif "rate limit" in error_msg:
            status = "rate_limited"
        elif "407" in error_msg:
            status = "proxy_error"
        elif "certificate" in error_msg:
            status = "ssl_error"
        else:
            status = "error"
            
        return f"RECOVERED (Account Status: {status})"



async def get_current_state(page: Page) -> dict:
    """Get current page state with proper element detection."""
    try:
        # Get state using exact class names and selectors we use elsewhere
        state = await page.evaluate('''
            () => {
                const selectors = {
                    startButton: 'input[type="submit"][class="Button EdgeButton EdgeButton--primary"][value="Start"]',
                    sendEmailButton: 'input[type="submit"][value="Send email"][class="Button EdgeButton--primary EdgeButton"]',
                    verifyInput: 'input[name="token"][class*="Form-textbox"]',
                    arkoseFrame: 'iframe[src*="arkoselabs"]',
                    continueButton: 'input[type="submit"][value="Continue to X"][class="Button EdgeButton--primary EdgeButton"]',
                    homeIndicators: [
                        '[data-testid="primaryColumn"]',
                        '[data-testid="SideNav_NewTweet_Button"]',
                        '[data-testid="AppTabBar_Home_Link"]'
                    ]
                };

                const findElement = (selector) => document.querySelector(selector) !== null;
                const findAny = (selectorList) => selectorList.some(s => document.querySelector(s) !== null);

                return {
                    hasStartButton: findElement(selectors.startButton),
                    hasSendEmailButton: findElement(selectors.sendEmailButton),
                    hasVerifyInput: findElement(selectors.verifyInput),
                    hasArkoseFrame: findElement(selectors.arkoseFrame),
                    hasContinueButton: findElement(selectors.continueButton),
                    hasHomeIndicators: findAny(selectors.homeIndicators),
                    url: window.location.href
                };
            }
        ''')
        
        logger.info(f"Current page state: {state}")
        return state
        
    except Exception as e:
        logger.error(f"Error getting page state: {e}")
        return {}

async def recover_account(page: Page, account: dict, proxy_config: dict) -> str:
    """Enhanced account recovery with proper retries and state transitions."""
    overall_retry_count = 3  # Number of complete recovery attempts
    
    for attempt in range(overall_retry_count):
        try:
            logger.info(f"Starting recovery attempt {attempt + 1}/{overall_retry_count} for account {account['account_no']}")

            # Quick home check before navigation
            if await is_on_home_page(page):
                logger.info("Already on home page")
                print_colored(text="ACCOUNT ALREADY RECOVERED", color=Fore.GREEN)
                return await check_account_status(account, proxy_config)

            # Navigate to access page
            if not await navigate_with_retry(page, 'https://x.com/account/access'):
                if attempt < overall_retry_count - 1:
                    continue
                return "NOT RECOVERED (Navigation Failed)"

            print_colored(text="UNLOCKING ACCOUNT...", color=Fore.YELLOW)

            # State handling loop - try multiple times within each attempt
            state_handle_attempts = 5  # Number of state transition attempts
            for state_attempt in range(state_handle_attempts):
                # Get accurate page state
                await asyncio.sleep(2)  # Wait for page to stabilize
                state = await get_current_state(page)
                logger.info(f"Current page state (attempt {state_attempt + 1}): {state}")

                # Handle states in order of priority
                if state['hasHomeIndicators'] or '/home' in state['url']:
                    logger.info("Reached home page")
                    return await check_account_status(account, proxy_config)

                if state['hasContinueButton']:
                    logger.info("Found Continue to X button")
                    await page.click('input[type="submit"][value="Continue to X"][class="Button EdgeButton--primary EdgeButton"]')
                    await asyncio.sleep(3)  # Wait longer for navigation
                    if await is_on_home_page(page):
                        return await check_account_status(account, proxy_config)

                if state['hasStartButton']:
                    logger.info("Found Start button")
                    await page.click('input[type="submit"][class="Button EdgeButton EdgeButton--primary"][value="Start"]')
                    await asyncio.sleep(2)
                    continue  # Check new state immediately

                if state['hasSendEmailButton']:
                    logger.info("Found Send Email button")
                    # Try email verification flow
                    if await handle_email_verification(page, account):
                        if await is_on_home_page(page):
                            return await check_account_status(account, proxy_config)
                    await asyncio.sleep(2)
                    continue

                if state['hasVerifyInput']:
                    logger.info("Found verification input field")
                    verification_code = await get_verification_code(account)
                    if verification_code:
                        await page.fill('input[name="token"][class*="Form-textbox"]', "")
                        await page.type('input[name="token"][class*="Form-textbox"]', verification_code, delay=10)
                        await page.click('input[type="submit"][value="Verify"]')
                        await asyncio.sleep(3)
                        continue

                if state['hasArkoseFrame']:
                    logger.info("Found authentication challenge")
                    if await handle_authentication(page, proxy_config):
                        if await is_on_home_page(page):
                            return await check_account_status(account, proxy_config)
                        continue

                # If no recognized state, try account access handler
                if await handle_account_access_page(page, account, proxy_config):
                    if await is_on_home_page(page):
                        return await check_account_status(account, proxy_config)

                # If we've tried all states multiple times, wait and try again
                if state_attempt == state_handle_attempts - 1:
                    logger.warning(f"State handling attempts exhausted in recovery attempt {attempt + 1}")
                
                await asyncio.sleep(2)  # Wait before next state check

            logger.error(f"Recovery attempt {attempt + 1} failed to reach home page")
            if attempt < overall_retry_count - 1:
                logger.info("Retrying complete recovery process")
                await asyncio.sleep(5)  # Wait before next complete attempt
                continue

        except Exception as e:
            logger.error(f"Error in recovery attempt {attempt + 1}: {e}")
            if attempt < overall_retry_count - 1:
                logger.info("Retrying after error")
                await asyncio.sleep(5)
                continue
            else:
                return f"NOT RECOVERED (Error: {str(e)[:100]})"

    logger.error("All recovery attempts exhausted")
    return "NOT RECOVERED (Max Attempts Reached)"

async def is_on_home_page(page: Page) -> bool:
    """
    Fast home page detection using both URL and key indicators.
    """
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

class CaptchaSolver:
    def __init__(self, proxy_config):
        self.proxy_config = proxy_config
        self.logger = logging.getLogger(__name__)
        
        # Updated PUBLIC_KEY to match payload
        self.PUBLIC_KEY = "0152B4EB-D2DC-460A-89A1-629838B529C9" 

        #self.PUBLIC_KEY = "0152B4EB-D2DC-460A-89A1-629"
        self.TWO_CAPTCHA_KEY = '4a5a819b86f4644d2fc770f53bdc40bc'
        
        # State tracking
        self.data_blob = None
        self.page = None
        self._last_frame = None
        self.session_token = None
        self.game_token = None
        
        # Initialize solver
        self.solver_2captcha = TwoCaptcha(self.TWO_CAPTCHA_KEY)
        self.solver_2captcha.timeout = 900  # 15 minute timeout
    
    async def setup_page_handlers(self, page):
        """Set up all necessary page handlers with enhanced error catching."""
        try:
            self.page = page
            
            # Setup request interception
            await page.route("**/*", self.handle_request)
            
            # Setup response handling
            page.on("response", self.handle_response)
            
            # Setup frame tracking
            page.on("framenavigated", self.handle_frame)
            
            # Handle console messages
            page.on("console", self.handle_console_message)
            
            # Enhanced WebSocket and data capture monitoring
            await page.add_init_script("""
                (() => {
                    // Override WebSocket for better data capture
                    const OriginalWebSocket = window.WebSocket;
                    window.WebSocket = function(url, protocols) {
                        const ws = new OriginalWebSocket(url, protocols);
                        ws.addEventListener('message', function(event) {
                            try {
                                const data = JSON.parse(event.data);
                                if (data.blob || data.data_blob || data.token) {
                                    console.log('CAPTURED_DATA:', JSON.stringify(data));
                                }
                            } catch (e) {}
                        });
                        return ws;
                    };

                    // Enhanced data blob capture
                    let originalPostMessage = window.postMessage;
                    window.postMessage = function(msg, targetOrigin, transfer) {
                        if (msg && typeof msg === 'object') {
                            if (msg.data && msg.data.blob) {
                                console.log('BLOB_CAPTURE:', JSON.stringify(msg.data));
                            }
                        }
                        return originalPostMessage.call(this, msg, targetOrigin, transfer);
                    };

                    // Arkose Labs specific capturing
                    Object.defineProperty(window, 'data_blob', {
                        set: function(value) {
                            console.log('DATA_BLOB_SET:', value);
                            this._data_blob = value;
                        },
                        get: function() {
                            return this._data_blob;
                        }
                    });
                })();
            """)
            
            self.logger.info("Enhanced captcha handlers setup completed")
            
        except Exception as e:
            self.logger.error(f"Error in setup_page_handlers: {e}")
            self.logger.error(traceback.format_exc())
            raise

    async def handle_console_message(self, msg):
        """Enhanced console message handler with better data extraction."""
        try:
            if msg.type in ['debug', 'log', 'info']:
                text = msg.text
                
                # Check for various data capture markers
                if any(marker in text for marker in ['CAPTURED_DATA:', 'BLOB_CAPTURE:', 'DATA_BLOB_SET:']):
                    self.logger.debug(f"Captured message: {text}")
                    
                    try:
                        if 'CAPTURED_DATA:' in text:
                            data = json.loads(text.replace('CAPTURED_DATA:', '').strip())
                            if data.get('blob'):
                                self.data_blob = data['blob']
                                self.logger.info(f"✓ Captured data_blob from WebSocket: {self.data_blob}")
                        
                        elif 'BLOB_CAPTURE:' in text:
                            data = json.loads(text.replace('BLOB_CAPTURE:', '').strip())
                            if data.get('blob'):
                                self.data_blob = data['blob']
                                self.logger.info(f"✓ Captured data_blob from postMessage: {self.data_blob}")
                        
                        elif 'DATA_BLOB_SET:' in text:
                            raw_blob = text.replace('DATA_BLOB_SET:', '').strip()
                            if raw_blob:
                                self.data_blob = raw_blob
                                self.logger.info(f"✓ Captured data_blob from setter: {self.data_blob}")
                    except json.JSONDecodeError:
                        pass

                # Extract data blob from frame parameters
                if 'arkoselabs.com' in text and 'data=' in text:
                    try:
                        data_param = re.search(r'data=([^&]+)', text)
                        if data_param:
                            self.data_blob = unquote(data_param.group(1))
                            self.logger.info(f"✓ Captured data_blob from URL parameters: {self.data_blob}")
                    except Exception as e:
                        self.logger.debug(f"Failed to extract data from URL: {e}")

        except Exception as e:
            self.logger.error(f"Error in console message handler: {e}")

    async def handle_request(self, route, request):
        """Fixed request handler to properly extract data_blob."""
        try:
            url = request.url
            method = request.method
            
            if PUBLIC_KEY in url and method == 'POST':
                post_data = request.post_data
                if post_data:
                    try:
                        if isinstance(post_data, str):
                            # Fix: Use imported parse_qs
                            params = parse_qs(post_data)
                            blob_list = params.get('data[blob]', [])
                            if blob_list:
                                self.data_blob = unquote(blob_list[0])
                                self.logger.info(f"✓ Captured data_blob from POST data: {self.data_blob}")
                                # Immediately try to solve after capturing blob
                                await self.solve_with_2captcha()
                        
                        try:
                            json_data = json.loads(post_data)
                            if 'blob' in json_data:
                                self.data_blob = json_data['blob']
                                self.logger.info(f"✓ Captured data_blob from JSON: {self.data_blob}")
                                # Immediately try to solve after capturing blob
                                await self.solve_with_2captcha()
                        except json.JSONDecodeError:
                            pass
                    except Exception as e:
                        self.logger.error(f"Error extracting data_blob: {e}")

            await route.continue_()
        except Exception as e:
            self.logger.error(f"Error in request handler: {e}")
            if not route.request._handled:
                await route.continue_()
    
    async def handle_response(self, response: Response):
        """Handle responses with enhanced data extraction."""
        try:
            url = response.url
            if 'arkoselabs.com' in url and response.request.method in ['POST', 'GET']:
                content_type = response.headers.get('content-type', '')
                if 'application/json' in content_type:
                    try:
                        json_body = await response.json()
                        if 'data_blob' in json_body:
                            self.data_blob = json_body['data_blob']
                            self.logger.info(f"✓ Captured data_blob from response: {self.data_blob}")
                            await self.take_frame_screenshot(url)
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            self.logger.error(f"Error in response handler: {e}")
    
    async def handle_frame(self, frame):
        """Enhanced frame handler with better data extraction."""
        try:
            url = frame.url
            if 'arkoselabs.com' in url:
                self.logger.info(f"Found Arkose frame: {url}")
                self._last_frame = frame
                
                if 'data=' in url:
                    try:
                        data_param = re.search(r'data=([^&]+)', url)
                        if data_param:
                            self.data_blob = unquote(data_param.group(1))
                            self.logger.info(f"✓ Captured data_blob from frame URL: {self.data_blob}")
                    except Exception as e:
                        self.logger.debug(f"Failed to extract data from frame URL: {e}")
                
                # Try to extract data_blob from frame's JavaScript context
                try:
                    data_blob = await frame.evaluate('''
                        () => {
                            return window.data_blob || 
                                   window.AKROSE_DATA_BLOB || 
                                   document.querySelector('[data-blob]')?.getAttribute('data-blob') ||
                                   null;
                        }
                    ''')
                    
                    if data_blob:
                        self.data_blob = data_blob
                        self.logger.info(f"✓ Captured data_blob from frame JS: {self.data_blob}")
                except Exception as e:
                    self.logger.debug(f"Failed to extract data from frame JS: {e}")
                    
        except Exception as e:
            self.logger.error(f"Error in frame handler: {e}")
    
    async def extract_data_blob_via_evaluate(self):
        """Extract data_blob with enhanced methods."""
        try:
            self.data_blob = await self.page.evaluate('''
                () => {
                    // Try multiple methods to find data_blob
                    return window.data_blob || 
                           window.AKROSE_DATA_BLOB ||
                           document.querySelector('[data-blob]')?.getAttribute('data-blob') ||
                           document.querySelector('script[type="text/javascript"]')?.textContent.match(/data_blob["']?\s*[:=]\s*["']([^"']+)["']/)?.[1] ||
                           null;
                }
            ''')
            if self.data_blob:
                self.logger.info(f"✓ Captured data_blob via evaluate: {self.data_blob}")
                await self.take_frame_screenshot(self.page.url)
        except Exception as e:
            self.logger.error(f"Error extracting data_blob via evaluate: {e}")

    async def solve_captcha_challenge(self) -> bool:
        """Main captcha solving workflow with enhanced retry."""
        try:
            if not self.data_blob:
                self.logger.info("Attempting to extract data_blob...")
                start_time = time.time()
                while not self.data_blob and time.time() - start_time < 60:
                    await self.extract_data_blob_via_evaluate()
                    if not self.data_blob:
                        for frame in self.page.frames:
                            if 'arkoselabs' in frame.url:
                                await self.handle_frame(frame)
                                if self.data_blob:
                                    break
                    await asyncio.sleep(2)
                
                if not self.data_blob:
                    self.logger.error("Failed to extract data_blob after 60 seconds")
                    return False
            
            self.logger.info("Starting captcha solving process with data_blob")
            
            # Try up to 3 times to solve
            for attempt in range(3):
                try:
                    token = await self.solve_with_2captcha(attempt=attempt+1)
                    if token:
                        self.logger.info("Successfully got captcha token")
                        submission_success = await self.submit_solution(token)
                        if submission_success:
                            self.logger.info("Captcha challenge completed successfully")
                            return True
                        else:
                            self.logger.error("Failed to submit captcha solution")
                        
                    self.logger.info(f"Captcha solve attempt {attempt + 1} failed, trying again...")
                    await asyncio.sleep(5)  # Wait between attempts
                    
                except Exception as e:
                    self.logger.error(f"Error in solve attempt {attempt + 1}: {e}")
                    await asyncio.sleep(5)
                    continue
                
            self.logger.error("Failed to solve captcha after 3 attempts")
            return False
                
        except Exception as e:
            self.logger.error(f"Error in captcha challenge: {e}")
            self.logger.error(traceback.format_exc())
            return False

    async def solve_with_2captcha(self, attempt=1, max_attempts=3):
        """Fixed 2captcha solver with exact payload format."""
        try:
            if not self.data_blob:
                self.logger.error("No data_blob available for 2Captcha.")
                return None

            self.solver_2captcha = TwoCaptcha(TWO_CAPTCHA_API_KEY)
            self.solver_2captcha.timeout = 900  # 15 minute timeout

            # Prepare proxy string
            try:
                proxy_ip = socket.gethostbyname(self.proxy_config['proxyAddress'])
                proxy_str = f"{self.proxy_config['proxyLogin']}:{self.proxy_config['proxyPassword']}@{proxy_ip}:{self.proxy_config['proxyPort']}"
            except socket.gaierror as e:
                self.logger.error(f"Failed to resolve proxy address: {e}")
                return None

            # Payload exactly matching the format shown
            payload = {
                'api_url': '',  # Must be first
                'key': self.TWO_CAPTCHA_KEY,  # Ensure the key is included
                'method': 'funcaptcha', 
                'publickey': self.PUBLIC_KEY,
                'pageurl': 'https://x.com/account/access',
                'proxy': proxy_str,
                'proxytype': 'HTTP',
                'cdn_url': '',
                'lurl': '',
                'surl': 'https://client-api.arkoselabs.com',
                'captchatype': 'funcaptcha',
                'useragent': USER_AGENT,
                'data': json.dumps({                           # Data as a JSON string
                    "blob": self.data_blob,
                    "blobFromArkoselabs": "1"
                }),
                'nojs': 0,
                'soft_id': 0  # This was missing
            }

            self.logger.info(f"Sending 2Captcha request (Attempt {attempt}/{max_attempts})")
            self.logger.debug(f"Payload: {json.dumps(payload, indent=2)}")

            async with httpx.AsyncClient() as client:
                try:
                    # Send request with ordered form data
                    response = await client.post(
                        'https://2captcha.com/in.php',
                        data=payload,
                        timeout=30.0
                    )
                    
                    response_text = response.text
                    self.logger.info(f"2captcha submit response: {response_text}")

                    # Handle the response
                    if response.status_code != 200:
                        raise Exception(f"2Captcha submit failed with status {response.status_code}")

                    if 'ERROR' in response_text:
                        self.logger.error(f"2Captcha error response: {response_text}")
                        if attempt < max_attempts:
                            await asyncio.sleep(5)
                            return await self.solve_with_2captcha(attempt=attempt + 1, max_attempts=max_attempts)
                        return None

                    # Try to parse JSON response
                    try:
                        result = response.json()
                    except json.JSONDecodeError:
                        if response_text.startswith('OK|'):
                            result = {'status': 1, 'request': response_text.split('|')[1]}
                        else:
                            self.logger.error(f"Invalid response format: {response_text}")
                            return None

                    if result.get('status') == 1:
                        captcha_id = result['request']
                        self.logger.info(f"Captcha submitted successfully with ID: {captcha_id}")
                        
                        token = await self._poll_2captcha_result(client, captcha_id, TWO_CAPTCHA_API_KEY)
                        if token:
                            self.logger.info(f"Got solution token: {token[:30]}...")
                            return token

                    if attempt < max_attempts:
                        await asyncio.sleep(5)
                        return await self.solve_with_2captcha(attempt=attempt + 1, max_attempts=max_attempts)
                        
                except Exception as e:
                    self.logger.error(f"Error in 2captcha request: {e}")
                    if attempt < max_attempts:
                        await asyncio.sleep(5)
                        return await self.solve_with_2captcha(attempt=attempt + 1, max_attempts=max_attempts)

            return None
        except Exception as e:
            self.logger.error(f"2Captcha error on attempt {attempt}: {e}")
            self.logger.error(traceback.format_exc())
            return None

    async def _poll_2captcha_result(self, client, captcha_id: str, api_key: str) -> str:
        """Enhanced polling with proper retry on unsolvable."""
        poll_interval = 15  # seconds between polls
        max_polls = 180  # 15 minutes total (180 * 5 seconds)
        
        for poll_num in range(max_polls):
            try:
                await asyncio.sleep(poll_interval)
                poll_url = f"https://2captcha.com/res.php?key={api_key}&action=get&id={captcha_id}&json=1"
                
                response = await client.get(poll_url)
                if response.status_code != 200:
                    self.logger.error(f"Poll request failed with status {response.status_code}")
                    continue
                
                result = response.json()
                self.logger.info(f"Poll response for captcha {captcha_id}: {result}")
                
                if result.get('status') == 1:
                    answer = result.get('request')
                    if answer and isinstance(answer, str) and len(answer) > 20:  # Basic validation of token
                        self.logger.info(f"Captcha solved successfully. Token length: {len(answer)}")
                        return answer
                    self.logger.error(f"Invalid answer format received: {answer}")
                    return None
                    
                if result.get('request') in ['CAPCHA_NOT_READY', 'CAPTCHA_NOT_READY']:
                    if poll_num % 12 == 0:  # Log every minute
                        self.logger.info(f"Captcha not ready, waited {poll_num * 5} seconds...")
                    continue
                    
                # Return None for unsolvable to trigger retry
                if result.get('request') == 'ERROR_CAPTCHA_UNSOLVABLE':
                    self.logger.info("Captcha reported as unsolvable - will retry with new submission")
                    return None
                    
                error_msg = result.get('request', '')
                if error_msg:
                    self.logger.error(f"2Captcha error: {error_msg}")
                    return None
                    
            except Exception as e:
                self.logger.error(f"Error during polling: {e}")
                continue
                
        self.logger.error("Polling timeout reached")
        return None

    async def submit_solution(self, token: str) -> bool:
        """Enhanced solution submission with comprehensive verification."""
        try:
            self.logger.info("Starting token submission...")

            # Collect all frames including nested ones
            frames = []
            async def collect_frames(frame):
                frames.append(frame)
                for child in frame.child_frames:
                    await collect_frames(child)

            await collect_frames(self.page.main_frame)

            arkose_frames = [f for f in frames if 'arkoselabs' in f.url]
            self.logger.info(f"Total Arkose frames found: {len(arkose_frames)}")

            if not arkose_frames:
                self.logger.error("No Arkose frames found for submission.")
                return False

            submission_success = False
            for frame in arkose_frames:
                try:
                    await frame.evaluate(f"""
                        (() => {{
                            const messages = [
                                {{
                                    eventId: "challenge-complete",
                                    payload: {{
                                        sessionToken: "{token}",
                                        type: "challengeComplete",
                                        status: "complete"
                                    }}
                                }},
                                {{
                                    eventId: "challenge-complete",
                                    metadata: {{
                                        url: "https://client-api.arkoselabs.com",
                                        sessionToken: "{token}",
                                        solvedTime: Date.now(),
                                        type: "game"
                                    }}
                                }},
                                {{ token: "{token}" }},
                                {{
                                    message: {{
                                        token: "{token}",
                                        type: "verification-complete",
                                        solved: true
                                    }}
                                }}
                            ];

                            // Try multiple posting strategies
                            const targets = [window.parent, window.top, window];
                            targets.forEach(target => {{
                                if (target) {{
                                    messages.forEach(msg => {{
                                        try {{
                                            target.postMessage(msg, "*");
                                            target.postMessage(JSON.stringify(msg), "*");
                                        }} catch (e) {{
                                            console.error('PostMessage failed:', e);
                                        }}
                                    }});
                                }}
                            }});

                            // Try direct token submission
                            try {{
                                if (window.arkose && typeof window.arkose.setAuthToken === 'function') {{
                                    window.arkose.setAuthToken("{token}");
                                }}
                            }} catch (e) {{
                                console.error('Direct token submission failed:', e);
                            }}
                        }})();
                    """)
                    
                    self.logger.info(f"Submitted token to frame: {frame.url}")
                    submission_success = True
                    
                except Exception as e:
                    self.logger.error(f"Error submitting to frame {frame.url}: {e}")
                    continue

            if not submission_success:
                self.logger.error("Failed to submit token to any Arkose frames.")
                return False

            # Enhanced success verification with multiple indicators
            for attempt in range(12):  # 60 seconds total
                try:
                    # Check direct navigation success
                    current_url = self.page.url
                    if current_url.endswith('/home'):
                        self.logger.info("Successfully redirected to home page")
                        return True

                    # Various success indicators
                    success_selectors = {
                        'home': [
                            '[data-testid="primaryColumn"]',
                            '[data-testid="AppTabBar_Home_Link"]',
                            '[data-testid="SideNav_NewTweet_Button"]',
                            'div[aria-label="Home timeline"]',
                            '[data-testid="HomeTimeline"]'
                        ],
                        'verification': [
                            'text="We sent you a code"',
                            '[data-testid="LoginForm_Login_Button"]',
                            'div:has-text("Enter the code")',
                            'input[name="verification_code"]',
                            'input[autocomplete="one-time-code"]'
                        ]
                    }

                    # Check all success indicators
                    for category, selectors in success_selectors.items():
                        for selector in selectors:
                            try:
                                await self.page.wait_for_selector(selector, timeout=5000)
                                self.logger.info(f"Found {category} indicator: {selector}")
                                return True
                            except Exception:
                                continue

                    # Check if challenge is no longer present
                    challenge_indicators = [
                        'iframe[src*="arkoselabs"]',
                        'iframe[src*="funcaptcha"]',
                        'iframe[title*="arkose"]'
                    ]

                    challenge_still_present = False
                    for indicator in challenge_indicators:
                        try:
                            await self.page.wait_for_selector(indicator, timeout=1000)
                            challenge_still_present = True
                            break
                        except Exception:
                            continue

                    if not challenge_still_present:
                        self.logger.info("Captcha challenge no longer present")
                        # Additional wait to ensure redirect completes
                        await asyncio.sleep(3)
                        return True

                    await asyncio.sleep(5)
                    self.logger.info(f"Verification attempt {attempt + 1}/12")

                except Exception as e:
                    self.logger.error(f"Error in verification attempt {attempt}: {e}")
                    await asyncio.sleep(5)

            self.logger.warning("No success indicators found after all attempts")
            return False

        except Exception as e:
            self.logger.error(f"Token submission failed: {e}")
            self.logger.error(traceback.format_exc())
            return False

    async def take_frame_screenshot(self, url: str):
        """Take debug screenshots with enhanced error handling."""
        try:
            screenshot_dir = 'screenshots'
            os.makedirs(screenshot_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            screenshot_path = os.path.join(screenshot_dir, f"frame_{timestamp}.png")
            
            await self.page.screenshot(path=screenshot_path, full_page=True)
            self.logger.info(f"✓ Screenshot saved: {screenshot_path}")
            
        except Exception as e:
            self.logger.error(f"Error taking screenshot: {e}")

async def main(account_no: str):
    """Enhanced main execution function."""
    accounts_df = pd.read_csv('recover_accounts.csv')

    account_row = accounts_df[accounts_df['account_no'] == account_no]
    if account_row.empty:
        logger.error(f"Account {account_no} not found in CSV file.")
        return

    account = account_row.iloc[0].to_dict()

    # Verify proxy configuration
    proxy_config = get_proxy_config(account)
    if not proxy_config:
        logger.error("Invalid proxy configuration")
        accounts_df.loc[accounts_df['account_no'] == account_no, 'recovery_status'] = "NOT RECOVERED (Bad Proxy)"
        accounts_df.to_csv('recover_accounts.csv', index=False)
        return

    # URL encode proxy credentials
    encoded_username = urllib.parse.quote(proxy_config['proxyLogin'], safe='')
    encoded_password = urllib.parse.quote(proxy_config['proxyPassword'], safe='')
    proxy_url = f"http://{encoded_username}:{encoded_password}@{proxy_config['proxyAddress']}:{proxy_config['proxyPort']}"
    logger.info(f"Constructed proxy URL with encoded credentials")

    # Test proxy speed and connectivity
    proxy_speed = await check_proxy_speed(proxy_config)
    if proxy_speed == float('inf'):
        logger.error("Proxy test failed")
        accounts_df.loc[accounts_df['account_no'] == account_no, 'recovery_status'] = "NOT RECOVERED (Bad Proxy)"
        accounts_df.to_csv('recover_accounts.csv', index=False)
        return

    # Verify IP address
    ip_address = await check_ip(proxy_config)
    logger.info(f"Using proxy IP: {ip_address}")
    if ip_address == "Unknown":
        logger.error("Failed to verify proxy connection")
        return

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

            # Launch browser with encoded proxy credentials
            browser = await p.chromium.launch(
                headless=True,
                proxy={
                    "server": proxy_url,
                    "username": encoded_username,
                    "password": encoded_password
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

            await context.route("**/*", lambda route: route.continue_())
            page = await context.new_page()

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

            # Configure timeouts and handlers
            page.set_default_navigation_timeout(60000)
            page.set_default_timeout(30000)
            page.on("console", lambda msg: logger.debug(f"Browser console {msg.type}: {msg.text}"))
            page.on("pageerror", lambda err: logger.error(f"Page error: {err}"))

            # Execute recovery process
            recovery_status = await recover_account(
                page=page,
                account=account,
                proxy_config=proxy_config
            )
            
            logger.info(f"Account {account['account_no']} final status: {recovery_status}")
            accounts_df.loc[accounts_df['account_no'] == account_no, 'recovery_status'] = recovery_status
            accounts_df.to_csv('recover_accounts.csv', index=False)

        except Exception as e:
            logger.error(f"Process error: {e}")
            logger.error(traceback.format_exc())
            accounts_df.loc[accounts_df['account_no'] == account_no, 'recovery_status'] = f"NOT RECOVERED (Error: {str(e)[:100]})"
            accounts_df.to_csv('recover_accounts.csv', index=False)

        finally:
            try:
                if 'browser' in locals():
                    await browser.close()
                    logger.info("Browser closed successfully")
            except Exception as e:
                logger.error(f"Error closing browser: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 recover_accounts.py <account_no>")
        sys.exit(1)

    account_no = sys.argv[1]

    try:
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main(account_no))
    except KeyboardInterrupt:
        print("\nScript terminated by user")
    except Exception as e:
        print(f"Fatal error: {str(e)}")
        traceback.print_exc()
