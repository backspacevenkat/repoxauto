import asyncio
import os
import logging
import random
import sys
from typing import Dict, Optional, Tuple
from datetime import datetime
import aiohttp
import aiohttp.client_exceptions
from aiohttp import ClientTimeout
from urllib.parse import quote, urljoin, urlparse, urlencode, parse_qsl
import aiofiles
import aiocsv
from playwright.async_api import (
    async_playwright,
    Playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError
)
import openai
from filelock import FileLock

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("oauth_setup.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
BROWSER_TIMEOUT = 240000  # 2 minutes
PAGE_TIMEOUT = 180000     # 1 minute
PAGE_LOAD_RETRIES = 6    # Number of retries for page load
PORT_RETRY_ATTEMPTS = 5
PORT_RETRY_DELAY = 60     # Reduced retry delay
MAX_BACKOFF_DELAY = 600   # Maximum backoff delay in seconds
RATE_LIMIT_DELAY = 30      # Base delay between operations in seconds
MAX_PORT_INCREMENT = 5  # Maximum number of port increments to try
PORT_SWITCH_DELAY = 30  # Delay before trying new port
OUTPUT_FOLDER = 'output'
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# OpenAI Configuration
OPENAI_API_KEY = "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"
openai.api_key = OPENAI_API_KEY

def generate_text_with_gpt4():
    """Generates a use case description using GPT-4."""
    prompt = (
        "I want to apply for Twitter Basic API access. Write a response to this question: "
        "Describe all of your use cases of Twitter's data and API. The response should be at least 600 characters long, "
        "unique, and avoid generic statements like 'analyzing sentiment'. Include various angles and specific use cases."
    )
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4-0613",
            messages=[
                {"role": "system", "content": "You are an expert in social media analytics and API usage."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1500
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Error generating text with GPT-4: {str(e)}")
        return (
            "I am building a comprehensive social media analytics platform that leverages Twitter's API for data collection, "
            "analysis, and visualization. The platform will focus on tracking engagement metrics, analyzing content performance, "
            "and identifying trending topics in specific industries. Key features include real-time monitoring of hashtag performance, "
            "sentiment analysis of user interactions, and automated report generation for stakeholder insights."
        )

class OAuthBrowserManager:
    """Singleton to manage OAuth browser instances"""
    _instances: Dict[str, 'OAuthSetupService'] = {}
    
    @classmethod
    def get_instance(cls, account_no: str) -> Optional['OAuthSetupService']:
        return cls._instances.get(account_no)
    
    @classmethod
    def set_instance(cls, account_no: str, instance: 'OAuthSetupService'):
        cls._instances[account_no] = instance
    
    @classmethod
    def remove_instance(cls, account_no: str):
        if account_no in cls._instances:
            del cls._instances[account_no]
    
    @classmethod
    async def cleanup_all(cls):
        for instance in cls._instances.values():
            await instance.cleanup_resources()
        cls._instances.clear()

def has_all_oauth_credentials(account_data: dict) -> bool:
    """Check if all required OAuth credentials exist and are non-empty"""
    required_fields = [
        'consumer_key', 'consumer_secret', 'bearer_token',
        'access_token', 'access_token_secret', 'client_id', 'client_secret'
    ]
    return all(account_data.get(field) and str(account_data.get(field)).strip() for field in required_fields)

class OAuthSetupService:
    # Precise selectors based on HTML structure
    credential_info = {
        "Client ID": {
            "value_selector": 'span.index__clientIdText--3GHLa',
            "credentials": {
                "client_id": 'span.index__clientIdText--3GHLa'
            }
        },
        "Client Secret": {
            "panel_text": "Client Secret",
            "save_button_text": "Yes, I saved it",
            "button_texts": ["Regenerate"],
            "confirm_button_text": "Yes, regenerate",
            "credentials": {
                "client_secret": 'xpath=//button[@aria-label="Copy Client Secret to clipboard"]/preceding-sibling::p[@data-testid="credential-information-credential"]'
            }
        },
        "API Key and Secret": {
            "panel_text": "API Key and Secret",
            "save_button_text": "Yes, I saved them",
            "button_texts": ["Generate", "Regenerate"],
            "confirm_button_text": "Yes, regenerate",
            "credentials": {
                "consumer_key": 'xpath=//button[@aria-label="Copy API Key to clipboard"]/preceding-sibling::p[@data-testid="credential-information-credential"]',
                "consumer_secret": 'xpath=//button[@aria-label="Copy API Key Secret to clipboard"]/preceding-sibling::p[@data-testid="credential-information-credential"]'
            }
        },
        "Bearer Token": {
            "panel_text": "Bearer Token",
            "save_button_text": "Yes, I saved it",
            "button_texts": ["Generate", "Regenerate"],
            "confirm_button_text": "Yes, regenerate",
            "credentials": {
                "bearer_token": 'xpath=//button[@aria-label="Copy Bearer Token to clipboard"]/preceding-sibling::p[@data-testid="credential-information-credential"]'
            }
        },
        "Access Token and Secret": {
            "panel_text": "Access Token and Secret",
            "save_button_text": "Yes, I saved them",
            "button_texts": ["Generate", "Regenerate"],
            "confirm_button_text": "Yes, regenerate",
            "credentials": {
                "access_token": 'xpath=//button[@aria-label="Copy Access Token to clipboard"]/preceding-sibling::p[@data-testid="credential-information-credential"]',
                "access_token_secret": 'xpath=//button[@aria-label="Copy Access Token Secret to clipboard"]/preceding-sibling::p[@data-testid="credential-information-credential"]'
            }
        }
    }

    def __init__(self, account_data: Dict):
        if not account_data:
            raise ValueError("Account data is required")
        
        self.account_data = account_data
        self.account_no = account_data['account_no']
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.max_retries = 3
        self.base_timeout = 120000
        self.retry_delay = 10
        
        OAuthBrowserManager.set_instance(self.account_no, self)

    async def wait_and_click(self, selector: str, timeout: int = 30000, delay: float = 0.5):
        try:
            element = await self.page.wait_for_selector(selector, timeout=timeout)
            await asyncio.sleep(delay)
            await element.click()
            logger.debug(f"Clicked element '{selector}'")
            return True
        except Exception as e:
            logger.error(f"Error clicking element '{selector}': {str(e)}")
            return False

    async def fill_form_field(self, selector: str, value: str):
        try:
            field = await self.page.wait_for_selector(selector, timeout=30000)
            await field.fill(value)
            logger.debug(f"Filled form field '{selector}' with value: {value}")
            return True
        except Exception as e:
            logger.error(f"Error filling form field '{selector}': {str(e)}")
            return False

    async def get_text_content(self, selector: str, timeout: int = 30000) -> Optional[str]:
        try:
            element = await self.page.wait_for_selector(selector, timeout=timeout)
            if element:
                text = await element.text_content()
                text = text.strip() if text else ""
                if text:
                    logger.debug(f"Extracted text from '{selector}': {text}")
                    return text
            logger.error(f"No text content found for selector '{selector}'")
            return None
        except Exception as e:
            logger.error(f"Error extracting text from '{selector}': {str(e)}")
            return None

    async def extract_credential(self, credential_name: str) -> Optional[Dict[str, str]]:
        try:
            info = self.credential_info.get(credential_name)
            if not info:
                logger.error(f"No info defined for '{credential_name}'")
                return None

            credentials = {}

            if credential_name == "Client ID":
                value = await self.get_text_content(info["value_selector"])
                if value:
                    credentials["client_id"] = value
                    logger.debug(f"Extracted 'client_id': {value}")
                else:
                    logger.error("Failed to extract 'client_id'")
                    return None
                return credentials

            panel_selector = f'div.index__TokenInfoPanel--3vyPY:has(div.index__tokenType--2IFoe:has-text("{info["panel_text"]}"))'
            panel = await self.page.query_selector(panel_selector)
            if not panel:
                logger.error(f"Panel for '{credential_name}' not found")
                page_content = await self.page.content()
                async with aiofiles.open(os.path.join(OUTPUT_FOLDER, f"missing_panel_{credential_name}_{self.account_no}.html"), 'w', encoding='utf-8') as f:
                    await f.write(page_content)
                return None

            button_found = False
            button_texts = info.get("button_texts", ["Regenerate"])
            clicked_button_text = None
            
            for attempt in range(3):
                try:
                    for text in button_texts:
                        button_selector = f'button:has-text("{text}")'
                        main_button = await panel.query_selector(button_selector)
                        
                        if main_button and await main_button.is_visible() and await main_button.is_enabled():
                            await main_button.scroll_into_view_if_needed()
                            await asyncio.sleep(1)
                            await main_button.click()
                            logger.debug(f"Clicked '{text}' button for '{credential_name}'")
                            clicked_button_text = text
                            button_found = True
                            break
                    
                    if button_found:
                        break
                        
                    if attempt < 2:
                        await asyncio.sleep(2 * (attempt + 1))
                        
                except Exception as e:
                    logger.warning(f"Button click attempt {attempt + 1} failed: {str(e)}")
                    if attempt < 2:
                        await asyncio.sleep(2 * (attempt + 1))
                    continue

            if not button_found:
                logger.error(f"Failed to find clickable button for '{credential_name}'")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                await self.save_error_screenshot(f"button_error_{credential_name}")
                return None

            # Handle confirmation if needed
            confirm_button_text = info.get("confirm_button_text")
            if confirm_button_text and clicked_button_text in ["Regenerate", "Generate"]:
                confirm_button_selector = f'button:has-text("{confirm_button_text}")'
                confirmation_present = await self.page.query_selector(confirm_button_selector)
                if confirmation_present:
                    await self.wait_and_click(confirm_button_selector)
                    await asyncio.sleep(3)

            # Extract credential values with retries
            for key, value_selector in info["credentials"].items():
                value = None
                for attempt in range(3):
                    try:
                        await asyncio.sleep(attempt * 2)
                        element = await self.page.wait_for_selector(value_selector, timeout=30000)
                        if element and await element.is_visible():
                            value = await self.get_text_content(value_selector)
                            if value:
                                credentials[key] = value
                                logger.debug(f"Extracted '{key}': {value}")
                                break
                    except Exception as e:
                        logger.warning(f"Error extracting '{key}' on attempt {attempt + 1}: {str(e)}")
                        if attempt < 2:
                            continue

                if not value:
                    logger.error(f"Failed to extract '{key}' after all attempts")
                    await self.save_error_screenshot(f"missing_credential_{key}")
                    return None

            # Click save button with retries
            save_button_selector = f'button:has-text("{info["save_button_text"]}")'
            save_button_clicked = False
            
            for attempt in range(3):
                try:
                    save_button = await self.page.wait_for_selector(save_button_selector + ":enabled", timeout=30000)
                    if save_button and await save_button.is_visible() and await save_button.is_enabled():
                        await save_button.scroll_into_view_if_needed()
                        await asyncio.sleep(1)
                        await save_button.click()
                        logger.debug(f"Clicked save button for '{credential_name}'")
                        save_button_clicked = True
                        break
                except Exception as e:
                    logger.warning(f"Error clicking save button on attempt {attempt + 1}: {str(e)}")
                    if attempt < 2:
                        await asyncio.sleep(2 * (attempt + 1))
                    continue

            if not save_button_clicked:
                logger.error(f"Failed to click save button for '{credential_name}'")
                await self.save_error_screenshot(f"save_button_error_{credential_name}")
                return None

            await asyncio.sleep(2)
            return credentials

        except Exception as e:
            logger.error(f"Error extracting credentials: {str(e)}")
            return None

    async def setup_browser_context(self) -> Optional[Tuple[Playwright, Browser, BrowserContext]]:
        """Setup browser context with optimized initialization"""
        try:
            # First check if there's an existing instance
            existing_instance = OAuthBrowserManager.get_instance(self.account_no)
            if existing_instance and existing_instance.browser and existing_instance.context:
                logger.info(f"Reusing existing browser instance for account {self.account_no}")
                return existing_instance.playwright, existing_instance.browser, existing_instance.context

            # Clean up any existing resources first
            await self.cleanup_resources()

            proxy_config = {
                'server': f"http://{self.account_data['proxy_url']}:{self.account_data['proxy_port']}",
                'username': str(self.account_data['proxy_username']),
                'password': str(self.account_data['proxy_password'])
            }

            # Start playwright
            self.playwright = await async_playwright().start()
            
            # Launch browser with proxy
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                proxy=proxy_config,
                args=['--no-sandbox']
            )

            # Create context with cookies
            self.context = await self.browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent=self.account_data.get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'),
                ignore_https_errors=True
            )

            if self.account_data.get('ct0') and self.account_data.get('auth_token'):
                await self.context.add_cookies([
                    {
                        'name': 'ct0',
                        'value': self.account_data['ct0'],
                        'domain': '.twitter.com',
                        'path': '/'
                    },
                    {
                        'name': 'auth_token',
                        'value': self.account_data['auth_token'],
                        'domain': '.twitter.com',
                        'path': '/'
                    }
                ])

            # Create new page
            self.page = await self.context.new_page()
            
            # Simple connectivity test
            await self.page.goto('about:blank', timeout=30000)
            
            # Register instance
            OAuthBrowserManager.set_instance(self.account_no, self)
            
            logger.info(f"Browser context setup completed for account {self.account_no}")
            return self.playwright, self.browser, self.context

        except Exception as e:
            logger.error(f"Error setting up browser context: {str(e)}")
            await self.cleanup_resources()
            return None

    async def cleanup_resources(self):
        """Clean up all browser resources"""
        try:
            if self.page:
                try:
                    await self.page.close()
                except Exception as e:
                    logger.warning(f"Error closing page: {str(e)}")
                self.page = None

            if self.context:
                try:
                    await self.context.close()
                except Exception as e:
                    logger.warning(f"Error closing context: {str(e)}")
                self.context = None

            if self.browser:
                try:
                    await self.browser.close()
                except Exception as e:
                    logger.warning(f"Error closing browser: {str(e)}")
                self.browser = None

            if self.playwright:
                try:
                    await self.playwright.stop()
                except Exception as e:
                    logger.warning(f"Error stopping playwright: {str(e)}")
                self.playwright = None

            OAuthBrowserManager.remove_instance(self.account_no)
            logger.info(f"Cleaned up resources for account {self.account_no}")

        except Exception as e:
            logger.error(f"Error in cleanup for account {self.account_no}: {str(e)}")
            # Reset all instances to None to ensure clean state
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None

    async def save_error_screenshot(self, error_type: str):
        try:
            if self.page:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_path = os.path.join(OUTPUT_FOLDER, f"{error_type}_{self.account_no}_{timestamp}.png")
                await self.page.screenshot(path=screenshot_path)
                
                html_path = os.path.join(OUTPUT_FOLDER, f"{error_type}_{self.account_no}_{timestamp}.html")
                page_content = await self.page.content()
                async with aiofiles.open(html_path, 'w', encoding='utf-8') as f:
                    await f.write(page_content)
                logger.debug(f"Debug files saved for error: {error_type}")
        except Exception as e:
            logger.error(f"Failed to save error screenshot: {str(e)}")

    async def get_credentials_from_existing_app(self) -> Optional[Dict[str, str]]:
        try:
            logger.info("Accessing Keys and Tokens tab...")
            await self.wait_and_click('button[role="tab"]:has-text("Keys and tokens")')
            await asyncio.sleep(3)

            credentials = {}

            # Extract Client ID
            client_id_data = await self.extract_credential("Client ID")
            if client_id_data:
                credentials.update(client_id_data)
            else:
                logger.error("Failed to extract Client ID")
                return None

            # Extract Client Secret
            client_secret_data = await self.extract_credential("Client Secret")
            if client_secret_data:
                credentials.update(client_secret_data)
            else:
                logger.error("Failed to extract Client Secret")
                return None

            # Extract API Key and Secret
            api_credentials = await self.extract_credential("API Key and Secret")
            if api_credentials:
                credentials.update(api_credentials)
            else:
                logger.error("Failed to extract API Key and Secret")
                return None

            # Extract Bearer Token
            bearer_token_data = await self.extract_credential("Bearer Token")
            if bearer_token_data:
                credentials.update(bearer_token_data)
            else:
                logger.error("Failed to extract Bearer Token")
                return None

            # Extract Access Token and Secret
            access_token_data = await self.extract_credential("Access Token and Secret")
            if access_token_data:
                credentials.update(access_token_data)
            else:
                logger.error("Failed to extract Access Token and Secret")
                return None

            expected_keys = [
                "client_id", "client_secret", "consumer_key", "consumer_secret",
                "bearer_token", "access_token", "access_token_secret"
            ]
            missing = [k for k in expected_keys if k not in credentials]
            if missing:
                raise Exception(f"Missing credentials: {', '.join(missing)}")

            logger.info("Successfully obtained all credentials from existing app")
            return credentials

        except Exception as e:
            logger.error(f"Error getting credentials from existing app: {str(e)}", exc_info=True)
            return None

    async def goto_with_retry(self, url: str, max_retries: int = PAGE_LOAD_RETRIES) -> bool:
        """Navigate to URL with retry mechanism and exponential backoff"""
        for attempt in range(max_retries):
            try:
                timeout = PAGE_TIMEOUT * (attempt + 1)  # Increase timeout with each retry
                logger.info(f"Attempting to navigate to {url} (attempt {attempt + 1}/{max_retries}, timeout: {timeout}ms)")
                await self.page.goto(url, timeout=timeout)
                await asyncio.sleep(RATE_LIMIT_DELAY * (attempt + 1))  # Add delay between attempts
                return True
            except Exception as e:
                logger.warning(f"Navigation attempt {attempt + 1} failed: {str(e)}")
                if attempt == max_retries - 1:
                    logger.error(f"All navigation attempts failed for {url}")
                    raise
                backoff_delay = RATE_LIMIT_DELAY * (2 ** attempt)  # Exponential backoff
                logger.info(f"Waiting {backoff_delay} seconds before retry...")
                await asyncio.sleep(backoff_delay)
        return False

    async def check_suspension_status(self) -> Optional[str]:
        """Check if account is suspended immediately after landing on developer portal"""
        try:
            # Check for suspension label
            suspension_label = await self.page.query_selector('span.Label.Label--red:has-text("suspended")')
            if suspension_label:
                is_visible = await suspension_label.is_visible()
                if is_visible:
                    logger.error(f"Account {self.account_no} is suspended")
                    await self.save_error_screenshot("suspension_detected")
                    return "Account is suspended"

            # Additional suspension text check
            suspension_text = await self.page.query_selector('text="This account is suspended"')
            if suspension_text:
                is_visible = await suspension_text.is_visible()
                if is_visible:
                    logger.error(f"Account {self.account_no} is suspended (text)")
                    await self.save_error_screenshot("suspension_text_detected")
                    return "Account is suspended"

            return None
        except Exception as e:
            logger.error(f"Error checking suspension status: {str(e)}")
            return None

    async def get_developer_credentials(self) -> Optional[Dict[str, str]]:
        """Get OAuth credentials with proxy port retry logic and optimized browser initialization"""
        initial_port = self.account_data['proxy_port']
        initial_error = None

        for port_increment in range(MAX_PORT_INCREMENT):  # Use global constant instead of self.MAX_PORT_INCREMENT
            try:
                current_port = str(int(initial_port) + port_increment)
                logger.info(f"Attempting OAuth setup with port {current_port} (increment {port_increment})")
                
                # Update proxy configuration with new port
                self.account_data['proxy_port'] = current_port
                self.proxy_config = {
                    'server': f"http://{self.account_data['proxy_url']}:{current_port}",
                    'username': str(self.account_data['proxy_username']),
                    'password': str(self.account_data['proxy_password'])
                }
                
                # Clean up any existing resources before new attempt
                await self.cleanup_resources()
                
                # Do initial setup with new port
                setup = await self.setup_browser_context()
                
                if not setup or len(setup) != 3:
                    logger.error(f"Browser context setup failed for port {current_port}")
                    continue
                    
                playwright, browser, context = setup
                
                if not all([playwright, browser, context]):
                    missing = []
                    if not playwright: missing.append('playwright')
                    if not browser: missing.append('browser')
                    if not context: missing.append('context')
                    logger.error(f"Missing browser components with port {current_port}: {', '.join(missing)}")
                    continue

                if not self.page:
                    logger.error(f"Page not initialized with port {current_port}")
                    continue

                try:
                    # Quick connection test before proceeding
                    logger.info("Testing connection to developer portal...")
                    await self.goto_with_retry('https://developer.twitter.com/en/portal/dashboard')
                    await asyncio.sleep(RATE_LIMIT_DELAY)

                    # Check for suspension immediately after landing
                    suspension_status = await self.check_suspension_status()
                    if suspension_status:
                        logger.error(f"Account {self.account_no} status: {suspension_status}")
                        # Store suspension status if needed
                        self.account_data['suspension_status'] = suspension_status
                        return {
                            'error': 'ACCOUNT_SUSPENDED',
                            'message': suspension_status
                        }

                    try:
                        signup_button = await self.page.wait_for_selector("text='Sign up for Free Account'", timeout=5000)
                        if signup_button:
                            logger.info("New account setup required...")
                            await signup_button.click()
                            await asyncio.sleep(2)

                            textarea = await self.page.wait_for_selector('textarea')
                            if textarea:
                                description = generate_text_with_gpt4()
                                await textarea.fill(description)
                                await asyncio.sleep(3)

                                for checkbox in ['resellTerms', 'voilationTerms', 'acceptedTerms']:
                                    checkbox_elem = await self.page.wait_for_selector(f'input[name="{checkbox}"]')
                                    if checkbox_elem:
                                        await checkbox_elem.click()
                                        await asyncio.sleep(1)

                                await self.wait_and_click('span:has-text("Submit")')
                                await asyncio.sleep(5)
                    except PlaywrightTimeoutError:
                        logger.info("No signup button found, assuming already registered")

                    logger.info("Navigating to Projects & Apps...")
                    await self.wait_and_click('span:has-text("Projects & Apps")')
                    await asyncio.sleep(3)

                    try:
                        standalone_app_selector = 'button.index__navItemButton--17Psw.index__isStandaloneApp--3NaIM'
                        app_button = await self.page.wait_for_selector(standalone_app_selector, timeout=5000)
                        if app_button:
                            await app_button.click()
                            await asyncio.sleep(2)
                            logger.info("Standalone app found and clicked")
                    except PlaywrightTimeoutError:
                        logger.info("No standalone app found, continuing with default app")

                    settings_cog_selector = 'span.Icon.Icon--cog[data-feather-tooltip-target]'
                    await self.wait_and_click(settings_cog_selector)
                    await asyncio.sleep(2)

                    edit_button_selector = 'span.Icon.Icon--editPencil.index__panelPencilIcon--19A1v'
                    edit_button = await self.page.query_selector(edit_button_selector)

                    if not edit_button:
                        logger.info("Setting up new app...")
                        await self.wait_and_click('span:has-text("Set up")')
                        await asyncio.sleep(2)

                        await self.wait_and_click('input[name="accessLevel"][value="READ_WRITE_DM"]')
                        await self.wait_and_click('input[name="appType"][value="WebApp"]')
                        await asyncio.sleep(1)

                        await self.fill_form_field('input[data-testid="callback-url-input"]', 'https://twitter.com')
                        await self.fill_form_field('input[data-testid="website-url-input"]', 'https://twitter.com')
                        await asyncio.sleep(1)

                        await self.wait_and_click('span:has-text("Save")')
                        await self.wait_and_click('span:has-text("Yes")')
                        await asyncio.sleep(3)

                        await self.wait_and_click('button[data-testid="done-button-oauth-2-keys-and-tokens"]')
                        await asyncio.sleep(2)
                        await self.wait_and_click('button:has-text("Yes, I saved it")')
                        await asyncio.sleep(2)
                    else:
                        logger.info("Found existing app setup")

                    # Try to get credentials with current port
                    credentials = await self.get_credentials_from_existing_app()
                    if credentials:
                        logger.info(f"Successfully obtained credentials using port {current_port}")
                        return credentials

                except PlaywrightTimeoutError as e:
                    logger.warning(f"Timeout with port {current_port}: {str(e)}")
                    if not initial_error:
                        initial_error = e
                    await self.save_error_screenshot(f"timeout_error_port_{current_port}")
                    continue

                except Exception as e:
                    logger.error(f"Error in developer portal with port {current_port}: {str(e)}", exc_info=True)
                    if not initial_error:
                        initial_error = e
                    await self.save_error_screenshot(f"developer_portal_error_port_{current_port}")
                    continue

                finally:
                    await self.cleanup_resources()
                    await asyncio.sleep(PORT_SWITCH_DELAY)  # Wait before trying next port

            except Exception as e:
                logger.error(f"Fatal error with port {current_port}: {str(e)}")
                if not initial_error:
                    initial_error = e
                if self.page:
                    await self.save_error_screenshot(f"fatal_error_port_{current_port}")
                await self.cleanup_resources()
                await asyncio.sleep(self.PORT_SWITCH_DELAY)
                continue

        # If all retries failed, log the initial error and return None
        if initial_error:
            logger.error(f"All port attempts failed. Initial error: {str(initial_error)}")
        return None

    async def check_account_status(self) -> str:
        """
        Checks the account status on the developer dashboard.
        Returns one of: 'suspended', 'unauthorized', 'Needs Verification', 'Active'
        """
        try:
            # First check if we're on a login/auth page
            current_url = self.page.url.lower()
            
            # Check for suspension or locked account with retries
            suspension_selector = 'h6[data-testid="unhealthy-callout-header"]'
            
            for attempt in range(3):
                try:
                    # Check for unhealthy account header
                    header = await self.page.wait_for_selector(
                        suspension_selector,
                        timeout=30000
                    )
                    if header:
                        text = await header.text_content()
                        text = text.lower()
                        if "suspended" in text:
                            logger.info(f"Account {self.account_no} is suspended")
                            await self.save_error_screenshot("suspended")
                            return "suspended"
                        elif "locked" in text:
                            logger.info(f"Account {self.account_no} needs verification")
                            await self.save_error_screenshot("needs_verification")
                            return "Needs Verification"
                except PlaywrightTimeoutError:
                    # No unhealthy header found, continue checking
                    pass

                # Check current URL for various states
                if any(pattern in current_url for pattern in ["flow/login", "oauth/authorize", "signin"]):
                    logger.info(f"Account {self.account_no} is unauthorized (on auth page)")
                    await self.save_error_screenshot("unauthorized")
                    return "unauthorized"

                # Check for verification/locked pages
                if any(pattern in current_url for pattern in ["account/access", "account/locked", "account_verification"]):
                    logger.info(f"Account {self.account_no} needs verification")
                    await self.save_error_screenshot("needs_verification")
                    return "Needs Verification"

                # Check for active state indicators
                try:
                    active_indicators = [
                        'div.index__TokenInfoPanel--3vyPY',
                        'button[role="tab"]:has-text("Keys and tokens")',
                        'div[role="navigation"]',
                        'div[data-testid="app-bar-dashboard"]'
                    ]
                    
                    for selector in active_indicators:
                        element = await self.page.query_selector(selector)
                        if element and await element.is_visible():
                            logger.info(f"Account {self.account_no} is active")
                            return "Active"
                except Exception as e:
                    logger.warning(f"Error checking active indicators on attempt {attempt + 1}: {str(e)}")
                    
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue

            # If we get here, take a screenshot and return unknown
            logger.error(f"Could not determine status for account {self.account_no}")
            await self.save_error_screenshot("status_unknown")
            return "Unknown"

        except Exception as e:
            logger.error(f"Error checking account status: {str(e)}")
            await self.save_error_screenshot("status_check_error")
            return "Unknown"

    async def test_service(self) -> bool:
        """Test if the service can create a page successfully"""
        try:
            # Initialize components
            setup = await self.setup_browser_context()
            if not setup or len(setup) != 3:
                logger.error("Failed to setup browser context")
                return False
            
            playwright, browser, context = setup
            
            if not all([playwright, browser, context]):
                missing = []
                if not playwright: missing.append("playwright")
                if not browser: missing.append("browser")
                if not context: missing.append("context")
                logger.error(f"Missing browser components: {', '.join(missing)}")
                return False
            
            try:
                # Create and verify test page
                test_page = await context.new_page()
                if not test_page:
                    logger.error("Failed to create test page")
                    return False
                
                # Test navigation with retry
                for attempt in range(2):
                    try:
                        await test_page.goto('about:blank', timeout=30000)
                        break
                    except Exception as e:
                        if attempt == 1:
                            logger.error(f"Navigation test failed: {str(e)}")
                            return False
                        await asyncio.sleep(1)
                
                # Test basic page operations
                try:
                    # Test JavaScript execution
                    await test_page.evaluate("window.innerWidth")
                    
                    # Test DOM manipulation
                    await test_page.evaluate("document.body.scrollHeight")
                    
                    # Test element creation
                    await test_page.evaluate("document.createElement('div')")
                    
                except Exception as e:
                    logger.error(f"Page operation test failed: {str(e)}")
                    return False
                
                # All tests passed
                logger.info(f"Service test passed for account {self.account_no}")
                return True
                
            except Exception as e:
                logger.error(f"Test page operations failed: {str(e)}")
                return False
                
            finally:
                # Clean up test resources
                if test_page:
                    await test_page.close()
                await self.cleanup_resources()
                
        except Exception as e:
            logger.error(f"Service test failed: {str(e)}")
            return False

    async def _wait_for_page_load(self, timeout: int = 120000) -> bool:
        """Wait for page to load with multiple selectors and verification steps"""
        try:
            if not self.page:
                return False

            # First verify basic page readiness
            try:
                await self.page.wait_for_load_state('domcontentloaded', timeout=timeout)
                await self.page.wait_for_load_state('networkidle', timeout=timeout)
                
                ready_state = await self.page.evaluate("document.readyState")
                logger.debug(f"Document ready state: {ready_state}")
                if ready_state != 'complete':
                    logger.warning("Document not fully loaded")
                    return False
            except Exception as e:
                logger.error(f"Basic page load check failed: {str(e)}")
                return False

            # Developer portal specific selectors
            portal_selectors = [
                'button[role="tab"]:has-text("Keys and tokens")',
                'span:has-text("Projects & Apps")',
                'div[role="tablist"]',
                'div.index__TokenInfoPanel--3vyPY',
                'div[role="main"]'
            ]
            
            # Try each selector with a shorter timeout
            for selector in portal_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=30000)
                    logger.debug(f"Found portal element: {selector}")
                    return True
                except Exception:
                    continue
            
            # Check for error states
            error_states = {
                'h1:has-text("Something went wrong")': "Error page",
                'div:has-text("Rate limit exceeded")': "Rate limited",
                'div:has-text("Page not found")': "404 error"
            }
            
            for selector, error_type in error_states.items():
                try:
                    if await self.page.wait_for_selector(selector, timeout=30000):
                        logger.error(f"Found error state: {error_type}")
                        return False
                except Exception:
                    continue
            
            # Final verification of page responsiveness
            try:
                await self.page.evaluate("window.innerWidth")
                await self.page.evaluate("document.body.scrollHeight")
                return True
            except Exception as e:
                logger.error(f"Page responsiveness check failed: {str(e)}")
                return False
            
        except Exception as e:
            logger.error(f"Error in page load verification: {str(e)}")
            return False

    async def verify_credentials(self, credentials: Dict[str, str]) -> bool:
        """Verify that all required credentials are present and valid"""
        try:
            required_keys = [
                "client_id", "client_secret", "consumer_key", "consumer_secret",
                "bearer_token", "access_token", "access_token_secret"
            ]
            
            # Check all keys exist
            missing = [key for key in required_keys if key not in credentials]
            if missing:
                logger.error(f"Missing credentials: {', '.join(missing)}")
                return False
                
            # Check all values are non-empty strings
            empty = [key for key, value in credentials.items() 
                    if not isinstance(value, str) or not value.strip()]
            if empty:
                logger.error(f"Empty credential values for: {', '.join(empty)}")
                return False
                
            # Basic format verification
            if not credentials["client_id"].startswith(""):  # Add your specific checks
                logger.error("Invalid client_id format")
                return False
                
            # Add more specific validation as needed
            
            logger.info("All credentials verified successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error verifying credentials: {str(e)}")
            return False
