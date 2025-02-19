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

async def check_proxy_speed(proxy_config: dict) -> float:
    """Test proxy speed with multiple endpoints."""
    try:
        username = quote(proxy_config['proxyLogin'])
        password = quote(proxy_config['proxyPassword'])
        proxy_url = f"http://{username}:{password}@{proxy_config['proxyAddress']}:{proxy_config['proxyPort']}"

        test_urls = [
            'https://api.ipify.org',
            'https://x.com/robots.txt',
            'https://client-api.arkoselabs.com'
        ]
        
        times = []
        transport = httpx.AsyncHTTPTransport(
            proxy=httpx.URL(proxy_url),
            verify=False,
            retries=1
        )
        
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(30.0),
            verify=False,
            follow_redirects=True,
            http2=False
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
        username = quote(proxy_config['proxyLogin'])
        password = quote(proxy_config['proxyPassword'])
        proxy_url = f"http://{username}:{password}@{proxy_config['proxyAddress']}:{proxy_config['proxyPort']}"

        ip_services = [
            'https://api.ipify.org',
            'https://ifconfig.me/ip',
            'https://icanhazip.com'
        ]
        
        transport = httpx.AsyncHTTPTransport(
            proxy=httpx.URL(proxy_url),
            verify=False,
            retries=1
        )
        
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(30.0),
            verify=False,
            follow_redirects=True,
            http2=False
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
        # Get email credentials with enhanced fallbacks
        email_address = account.get('recovery_email', account.get('email', account.get('username')))
        email_password = account.get('recovery_email_password', account.get('email_password', account.get('password')))
        email_server = account.get('email_server', account.get('imap_server', IMAP_HOST))
        
        if not email_address or not email_password:
            logger.error("Missing email credentials - Checked recovery_email, email, username")
            logger.error("Missing email password - Checked recovery_email_password, email_password, password")
            return None
            
        # Clean up email address if needed
        email_address = email_address.strip().lower()
        if '@' not in email_address and '.' not in email_address:
            # If just username provided, append domain
            email_address = f"{email_address}@{email_server}"
            
        logger.info(f"Connecting to IMAP server {email_server}:{IMAP_PORT}")
        
        # Connect to IMAP server with timeout and SSL context
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        socket.setdefaulttimeout(30)  # 30 second timeout
        
        try:
            imap = imaplib.IMAP4_SSL(email_server, IMAP_PORT, ssl_context=ssl_context)
        except (socket.gaierror, socket.timeout) as e:
            logger.error(f"Failed to connect to IMAP server: {e}")
            return None
        
        # Login with proper credentials
        try:
            imap.login(email_address, email_password)
            logger.info("Successfully logged into IMAP")
        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP login failed: {e}")
            return None

        # Select inbox
        imap.select('INBOX')
        
        # Search ALL messages without date filter
        search_criteria = 'ALL'
        
        for attempt in range(3):  # Try for 1 minute
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
                            
                            # Common patterns for both subject and body
                            code_patterns = [
                                # Verification code patterns
                                r'(\d{6})[^\d]*verification code',
                                r'verification code[^\d]*(\d{6})',
                                r'(\d{6})\s*is your\s*(?:X|Twitter) code',
                                r'Verification code:\s*(\d{6})',
                                r'Code:\s*(\d{6})',
                                r'Your code is\s*(\d{6})',
                                r'Your verification code is\s*(\d{6})',
                                r'Use this code to verify:\s*(\d{6})',
                                r'Enter this code:\s*(\d{6})',
                                r'Enter code\s*(\d{6})',
                                r'code to continue[^\d]*(\d{6})',
                                r'here\'s your code[^\d]*(\d{6})',
                                r'(\d{6})\s+is your[^$]+verification code',
                                r'confirmation code[^\d]*(\d{6})',
                                r'security code[^\d]*(\d{6})',
                                r'access code[^\d]*(\d{6})',
                                r'login code[^\d]*(\d{6})',
                                r'one-time code[^\d]*(\d{6})',
                                r'temporary code[^\d]*(\d{6})',
                                r'(\d{6})\s*to\s*(?:verify|confirm|access)',
                                
                                # Last resort patterns
                                r'code[^\d]{0,20}(\d{6})',
                                r'(\d{6})[^\d]{0,20}code',
                                r'(\d{6})'  # Last resort - any 6 digits
                            ]
                            
                            # Check subject first
                            for pattern in code_patterns:
                                match = re.search(pattern, subject, re.IGNORECASE)
                                if match:
                                    code = match.group(1)
                                    logger.info(f"Found code in subject: {code}")
                                    codes_with_dates.append((code, email_date))
                                    break
                            
                            # If not found in subject, check message body
                            if not codes_with_dates:
                                # Get body content with better error handling
                                body = ""
                                try:
                                    if message.is_multipart():
                                        # Handle multipart messages
                                        for part in message.walk():
                                            if part.get_content_type() == "text/plain":
                                                try:
                                                    payload = part.get_payload(decode=True)
                                                    if payload:
                                                        try:
                                                            body = payload.decode()
                                                        except UnicodeDecodeError:
                                                            body = payload.decode('utf-8', 'ignore')
                                                        break
                                                except Exception as e:
                                                    logger.error(f"Error decoding multipart payload: {e}")
                                                    continue
                                    else:
                                        # Handle non-multipart messages
                                        try:
                                            payload = message.get_payload(decode=True)
                                            if payload:
                                                try:
                                                    body = payload.decode()
                                                except UnicodeDecodeError:
                                                    body = payload.decode('utf-8', 'ignore')
                                        except Exception as e:
                                            logger.error(f"Error decoding non-multipart payload: {e}")
                                            
                                    # If we still don't have a body, try alternative methods
                                    if not body:
                                        # Try getting raw payload as string
                                        body = str(message.get_payload())
                                        
                                except Exception as e:
                                    logger.error(f"Error extracting email body: {e}")
                                
                                logger.info("Checking email body for verification code")
                                
                                # Clean up body text
                                body = re.sub(r'\s+', ' ', body)  # Normalize whitespace
                                body = body.strip()
                                
                                # Look for codes in body with additional context validation
                                for pattern in code_patterns:
                                    matches = list(re.finditer(pattern, body, re.IGNORECASE))
                                    for match in matches:
                                        code = match.group(1)
                                        # Get surrounding context
                                        start = max(0, match.start() - 50)
                                        end = min(len(body), match.end() + 50)
                                        context = body[start:end]
                                        
                                        # Validate code format
                                        if len(code) == 6 and code.isdigit():
                                            # Check if context suggests this is a verification code
                                            context_lower = context.lower()
                                            verification_terms = [
                                                'verify', 'verification', 'confirm', 'access',
                                                'code', 'token', 'authenticate', 'login'
                                            ]
                                            if any(term in context_lower for term in verification_terms):
                                                logger.info(f"Found code {code} in body with context: {context.strip()}")
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
    """Enhanced verification page detection with multiple methods."""
    try:
        # First check URL (fastest)
        current_url = page.url.lower()
        if any(x in current_url for x in ['verify', 'verification', 'confirm', 'access']):
            logger.info(f"Found verification indicator in URL: {current_url}")
            
            # Check page content for verification text
            content = await page.content()
            content_lower = content.lower()
            text_indicators = [
                'verify your email',
                'verification code',
                'enter the code',
                'check your email',
                'we sent you a code',
                'verify your account',
                'confirm your email'
            ]
            if any(indicator in content_lower for indicator in text_indicators):
                logger.info("Found verification text in page content")
                return True
        
        # Check for verification elements
        verification_indicators = [
            # Text indicators
            ':text("We sent you a code")',
            ':text("Enter Verification Code")',
            ':text("Check your email")',
            ':text("for your verification code")',
            ':text("Didn\'t receive an email?")',
            ':text("Enter it below to verify")',
            ':text("Enter verification code")',
            
            # Input fields
            'input[name="verification_code"]',
            'input[name="token"]',
            'input[autocomplete="one-time-code"]',
            '[data-testid="ocfEnterTextTextInput"]',
            'input[type="text"][class*="Form-textbox"]',
            
            # Buttons
            'input[type="submit"][value="Send email"]',
            'input[type="submit"][value="Verify"]',
            
            # Containers
            'div:has-text("Enter the code")',
            'div:has-text("Check your email")',
            'div[class*="verification"]',
            'form[data-testid="LoginForm"]'
        ]
        
        for indicator in verification_indicators:
            try:
                element = await page.wait_for_selector(indicator, timeout=3000)
                if element:
                    logger.info(f"Found verification indicator: {indicator}")
                    return True
            except Exception:
                continue
        
        return False
        
    except Exception as e:
        logger.error(f"Error checking verification page: {e}")
        return False

async def handle_email_verification(page: Page, account: dict) -> bool:
    """Enhanced email verification handler with better state handling and retries."""
    try:
        logger.info("Starting email verification process...")
        
        # Wait for page to stabilize
        await page.wait_for_load_state('networkidle')
        await asyncio.sleep(2)
        
        # Try multiple selectors for Send Email button with better error handling
        send_email_selectors = [
            'input[type="submit"][value="Send email"][class="Button EdgeButton--primary EdgeButton"]',
            'input[type="submit"][value="Send email"]',
            'button:has-text("Send email")',
            'button[type="submit"]:has-text("Send")',
            'input[type="submit"][class*="EdgeButton--primary"]',
            '[data-testid="LoginForm"] input[type="submit"]',
            'form[data-testid="LoginForm"] button[type="submit"]'
        ]
        
        # Try to find and click Send Email button with retries
        send_email_clicked = False
        retry_attempts = 1
        
        for attempt in range(retry_attempts):
            for selector in send_email_selectors:
                try:
                    # Check if button is visible and clickable
                    button = await page.wait_for_selector(selector, timeout=5000, state='visible')
                    if button:
                        # Check if button is enabled
                        is_disabled = await button.get_attribute('disabled')
                        if not is_disabled:
                            logger.info(f"Found clickable Send Email button with selector: {selector}")
                            await button.click()
                            send_email_clicked = True
                            await asyncio.sleep(3)  # Wait longer after click
                            break
                except Exception as e:
                    logger.debug(f"Button not found with selector {selector}: {e}")
                    continue
                    
            if send_email_clicked:
                break
                
            if attempt < retry_attempts - 1:
                logger.info(f"Retrying to find Send Email button (attempt {attempt + 1}/{retry_attempts})")
                await asyncio.sleep(2)
                
        if not send_email_clicked:
            logger.info("No Send Email button found or clicked, checking for verification input directly")
        
        # Enhanced verification input selectors
        verify_input_selectors = [
            'input[name="token"][class*="Form-textbox"]',
            'input[name="verification_code"]',
            'input[autocomplete="one-time-code"]',
            '[data-testid="ocfEnterTextTextInput"]',
            'input[type="text"][class*="Form-textbox"]',
            'input[type="text"][name*="verify"]',
            'input[type="text"][name*="code"]',
            'input[type="text"][placeholder*="code"]',
            'input[type="text"][placeholder*="verification"]'
        ]
        
        # Try to find verification input with retries
        verify_code_input = None
        retry_attempts = 2
        
        for attempt in range(retry_attempts):
            for selector in verify_input_selectors:
                try:
                    verify_code_input = await page.wait_for_selector(selector, timeout=5000, state='visible')
                    if verify_code_input:
                        # Verify input is enabled
                        is_disabled = await verify_code_input.get_attribute('disabled')
                        if not is_disabled:
                            logger.info(f"Found enabled verification input with selector: {selector}")
                            break
                except Exception:
                    continue
                    
            if verify_code_input:
                break
                
            if attempt < retry_attempts - 1:
                logger.info(f"Retrying to find verification input (attempt {attempt + 1}/{retry_attempts})")
                await asyncio.sleep(2)
                
        if not verify_code_input:
            logger.error("Could not find verification code input after all attempts")
            return False
            
        # Get and enter verification code
        verification_code = await get_verification_code(account)
        if not verification_code:
            logger.error("Failed to get verification code")
            return False
            
        logger.info(f"Entering verification code: {verification_code}")
        await verify_code_input.fill("")  # Clear first
        await verify_code_input.type(verification_code, delay=10)
        
        # Try multiple selectors for Verify button
        verify_button_selectors = [
            'input[type="submit"][value="Verify"][class="Button EdgeButton--primary EdgeButton"]',
            'input[type="submit"][value="Verify"]',
            'button:has-text("Verify")',
            'button[type="submit"]:has-text("Verify")',
            'input[type="submit"][class*="EdgeButton--primary"]'
        ]
        
        # Try to find and click Verify button
        verify_clicked = False
        for selector in verify_button_selectors:
            try:
                button = await page.wait_for_selector(selector, timeout=3000)
                if button:
                    logger.info(f"Found Verify button with selector: {selector}")
                    await button.click()
                    verify_clicked = True
                    await asyncio.sleep(2)
                    break
            except Exception:
                continue
                
        if not verify_clicked:
            logger.error("Could not find Verify button")
            return False
            
        # Enhanced success verification
        success_attempts = 3  # 20 seconds total
        for attempt in range(success_attempts):
            # Check for home page first
            if await is_on_home_page(page):
                logger.info("Successfully reached home page after verification")
                return True
                
            # Check for Continue to X button
            continue_button_selectors = [
                'input[type="submit"][value="Continue to X"][class="Button EdgeButton--primary EdgeButton"]',
                'input[type="submit"][value="Continue to X"]',
                'button:has-text("Continue to X")',
                'button[type="submit"]:has-text("Continue")'
            ]
            
            for selector in continue_button_selectors:
                try:
                    button = await page.wait_for_selector(selector, timeout=2000)
                    if button:
                        logger.info(f"Found Continue button with selector: {selector}")
                        await button.click()
                        await asyncio.sleep(2)
                        if await is_on_home_page(page):
                            logger.info("Successfully reached home page after Continue")
                            return True
                        break
                except Exception:
                    continue
                    
            # Check for error messages
            error_selectors = [
                'text="Invalid code"',
                'text="Code expired"',
                'text="Please try again"',
                '.error-message',
                '[data-testid="error"]'
            ]
            
            for selector in error_selectors:
                try:
                    error = await page.wait_for_selector(selector, timeout=1000)
                    if error:
                        error_text = await error.text_content()
                        logger.error(f"Found error message: {error_text}")
                        return False
                except Exception:
                    continue
                    
            await asyncio.sleep(2)
            logger.info(f"Verification success check attempt {attempt + 1}/{success_attempts}")
            
        logger.error("Could not verify successful verification")
        return False

    except Exception as e:
        logger.error(f"Error in email verification: {e}")
        logger.error(traceback.format_exc())
        return False

async def get_current_state(page: Page) -> dict:
    """Get detailed current page state."""
    try:
        # Get state using JavaScript evaluation
        state = await page.evaluate('''
            () => {
                const selectors = {
                    startButton: 'input[type="submit"][value="Start"][class*="EdgeButton--primary"]',
                    sendEmailButton: 'input[type="submit"][value="Send email"][class*="EdgeButton--primary"]',
                    verifyInput: 'input[name="token"][class*="Form-textbox"]',
                    verifyButton: 'input[type="submit"][value="Verify"][class*="EdgeButton--primary"]',
                    continueButton: 'input[type="submit"][value="Continue to X"][class*="EdgeButton--primary"]',
                    arkoseFrame: 'iframe[src*="arkoselabs"]',
                    homeIndicators: [
                        '[data-testid="primaryColumn"]',
                        '[data-testid="SideNav_NewTweet_Button"]',
                        '[data-testid="AppTabBar_Home_Link"]'
                    ],
                    verificationIndicators: [
                        '[data-testid="LoginForm"]',
                        '[data-testid="ocfEnterTextTextInput"]',
                        'input[name="verification_code"]',
                        'input[name="token"]',
                        'input[autocomplete="one-time-code"]'
                    ]
                };

                const findElement = (selector) => document.querySelector(selector) !== null;
                const findAny = (selectorList) => selectorList.some(s => document.querySelector(s) !== null);

                return {
                    hasStartButton: findElement(selectors.startButton),
                    hasSendEmailButton: findElement(selectors.sendEmailButton),
                    hasVerifyInput: findElement(selectors.verifyInput),
                    hasVerifyButton: findElement(selectors.verifyButton),
                    hasContinueButton: findElement(selectors.continueButton),
                    hasArkoseFrame: findElement(selectors.arkoseFrame),
                    hasHomeIndicators: findAny(selectors.homeIndicators),
                    hasVerificationIndicators: findAny(selectors.verificationIndicators),
                    url: window.location.href,
                    title: document.title
                };
            }
        ''')
        
        logger.info(f"Current page state: {json.dumps(state, indent=2)}")
        return state
        
    except Exception as e:
        logger.error(f"Error getting page state: {e}")
        return {}

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

async def recover_account(account_data: dict, proxy_config: dict) -> str:
    """Main account recovery function."""
    try:
        overall_retry_count = 1  # Number of complete recovery attempts
        
        # Ensure we have all required credentials
        required_fields = ['email', 'email_password', 'auth_token', 'ct0']
        for field in required_fields:
            if not account_data.get(field):
                logger.error(f"Missing required field: {field}")
                return f"NOT RECOVERED (Missing {field})"
        
        # Create standardized account dict with all possible credential fields
        account = {
            'account_no': account_data.get('account_no'),
            'email': account_data.get('email'),
            'email_password': account_data.get('email_password'),
            'recovery_email': account_data.get('email'),  # Use same email as recovery
            'recovery_email_password': account_data.get('email_password'),  # Use same password
            'username': account_data.get('login'),
            'password': account_data.get('password'),
            'auth_token': account_data.get('auth_token'),
            'ct0': account_data.get('ct0'),
            'user_agent': account_data.get('user_agent', USER_AGENT)
        }
        
        logger.info(f"Starting recovery for account {account['account_no']} with email {account['email']}")
        
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
                        username = quote(proxy_config['proxyLogin'])
                        password = quote(proxy_config['proxyPassword'])
                        proxy_url = f"http://{username}:{password}@{proxy_config['proxyAddress']}:{proxy_config['proxyPort']}"

                        # Launch browser in headless mode with additional settings
                        browser = await p.chromium.launch(
                            headless=True,  # Ensure headless mode
                            proxy={
                                "server": proxy_url,
                                "username": proxy_config['proxyLogin'],
                                "password": proxy_config['proxyPassword']
                            },
                            args=[
                                *browser_args,
                                '--headless=new',  # Use new headless mode
                                '--disable-gpu',
                                '--no-sandbox',
                                '--disable-setuid-sandbox'
                            ],
                            devtools=False  # Disable devtools in headless mode
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

                        # Wait for page to load and stabilize
                        await page.wait_for_load_state('networkidle')
                        logger.info("Page loaded, checking verification type...")

                        # Wait for initial page load
                        await page.wait_for_load_state('networkidle')
                        await asyncio.sleep(2)  # Additional wait for stability

                        # State handling loop
                        state_handle_attempts = 5
                        for state_attempt in range(state_handle_attempts):
                            # Take screenshot for debugging
                            await page.screenshot(path=f'debug_screenshot_{state_attempt}.png')
                            
                            # Get current state
                            state = await get_current_state(page)
                            logger.info(f"Current state (attempt {state_attempt + 1}): {json.dumps(state, indent=2)}")
                            
                            # Check states in priority order
                            if state['hasHomeIndicators'] or '/home' in state['url']:
                                logger.info("Already on home page")
                                return "RECOVERED (Success)"
                                
                            if state['hasSendEmailButton']:
                                logger.info("Found Send email button")
                                await page.click('input[type="submit"][value="Send email"][class="Button EdgeButton--primary EdgeButton"]')
                                await asyncio.sleep(2)
                                continue
                                
                            if state['hasVerifyInput']:
                                logger.info("Found verification code input")
                                verification_code = await get_verification_code(account)
                                if verification_code:
                                    logger.info(f"Entering verification code: {verification_code}")
                                    await page.fill('input[name="token"][class*="Form-textbox"]', "")
                                    await page.type('input[name="token"][class*="Form-textbox"]', verification_code, delay=10)
                                    
                                    if state['hasVerifyButton']:
                                        logger.info("Clicking Verify button")
                                        await page.click('input[type="submit"][value="Verify"][class="Button EdgeButton--primary EdgeButton"]')
                                        await asyncio.sleep(2)
                                        continue
                                else:
                                    logger.error("Failed to get verification code")
                                    break
                                    
                            if state['hasStartButton']:
                                logger.info("Found Start button")
                                await page.click('input[type="submit"][value="Start"][class*="EdgeButton--primary"]')
                                await asyncio.sleep(2)
                                continue
                                
                            if state['hasContinueButton']:
                                logger.info("Found Continue to X button")
                                try:
                                    # Try multiple selectors for Continue button
                                    continue_button_selectors = [
                                        'input[type="submit"][value="Continue to X"][class="Button EdgeButton--primary EdgeButton"]',
                                        'input[type="submit"][value="Continue to X"]',
                                        'button:has-text("Continue to X")',
                                        'button[type="submit"]:has-text("Continue")',
                                        '[data-testid="confirmationSheetConfirm"]'
                                    ]
                                    
                                    for selector in continue_button_selectors:
                                        try:
                                            button = await page.wait_for_selector(selector, timeout=5000, state='visible')
                                            if button:
                                                logger.info(f"Found Continue button with selector: {selector}")
                                                await button.click()
                                                await asyncio.sleep(3)  # Wait longer after click
                                                
                                                # Check for success after click
                                                for _ in range(10):  # 20 seconds total
                                                    if await is_on_home_page(page):
                                                        logger.info("Successfully reached home page after Continue")
                                                        return "RECOVERED (After Continue)"
                                                    await asyncio.sleep(2)
                                                break  # Break after first successful click
                                        except Exception as e:
                                            logger.debug(f"Button not found with selector {selector}: {e}")
                                            continue
                                    
                                    # If we get here, continue button was clicked but home page not reached
                                    logger.warning("Continue button clicked but home page not reached")
                                    continue
                                    
                                except Exception as e:
                                    logger.error(f"Error handling Continue button: {e}")
                                    continue
                                
                            if state['hasArkoseFrame']:
                                logger.info("Found captcha challenge")
                                captcha_solver = CaptchaSolver(proxy_config)
                                await captcha_solver.setup_page_handlers(page)
                                if await captcha_solver.solve_captcha_challenge():
                                    if await is_on_home_page(page):
                                        return "RECOVERED (After Captcha)"
                                    continue
                                else:
                                    logger.error("Captcha solving failed")
                                    break
                            # Handle any unexpected popups
                            await handle_unexpected_popups(page)

                            # If no recognized state found, check if we're stuck
                            if not any([
                                state['hasHomeIndicators'],
                                state['hasSendEmailButton'],
                                state['hasVerifyInput'],
                                state['hasStartButton'],
                                state['hasContinueButton'],
                                state['hasArkoseFrame']
                            ]):
                                logger.warning("No recognized state found")
                                # Log current state for debugging
                                logger.info(f"Current URL: {page.url}")
                                logger.info(f"Current content: {await page.content()}")
                                
                                # Check if we're on a verification page but missed the indicators
                                if await is_email_verification_page(page):
                                    logger.info("Found email verification page through secondary check")
                                    if await handle_email_verification(page, account):
                                        if await is_on_home_page(page):
                                            return "RECOVERED (After Email Verification)"
                                        continue
                                
                            # Wait before next state check
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
