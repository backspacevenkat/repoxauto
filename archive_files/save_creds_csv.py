import asyncio
import os
import logging
import random
import sys
import time
import pandas as pd  # Add this import
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
import aiohttp
import aiofiles
import aiocsv
from playwright.async_api import async_playwright, Playwright, TimeoutError as PlaywrightTimeoutError

import openai
import requests

# =========================
# Configuration and Setup
# =========================

# Configure logging with reduced verbosity
logging.basicConfig(
    level=logging.INFO,  # Set to INFO; change to DEBUG for more detailed logs
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("twitter_account_manager.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

BROWSER_TIMEOUT = 60000  # 60 seconds
PAGE_TIMEOUT = 30000      # 30 seconds
PORT_RETRY_ATTEMPTS = 5
PORT_RETRY_DELAY = 30     # Reduced retry delay
MAX_BACKOFF_DELAY = 300   # Maximum backoff delay in seconds

# Constants
ACCOUNTS_FILE = 'accounts6.csv'
OUTPUT_FOLDER = 'output'

# Ensure the output directory exists
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Fetch OpenAI API key from environment variables for security
#OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_KEY = "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"
openai.api_key = "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"
if not OPENAI_API_KEY:
    logger.error("OpenAI API key not found. Please set the OPENAI_API_KEY environment variable.")
    sys.exit(1)
openai.api_key = OPENAI_API_KEY

# Result columns to update in CSV
RESULT_COLUMNS = [
    'account_status', 'language_status', 'developer_status',
    'access_token', 'access_token_secret', 'bearer_token',
    'client_id', 'client_secret', 'consumer_key', 'consumer_secret'
]
MAX_CONCURRENT_TASKS = 4  # Adjust based on your system's capabilities

# Create an asyncio lock for serializing CSV updates
csv_lock = asyncio.Lock()

# =========================
# Helper Functions
# =========================

def generate_text_with_gpt4():
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
        )  # Fallback text

# =========================
# Main Class
# =========================

class TwitterAccountManager:
    # Precise selectors based on provided HTML structure
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
            "button_texts": ["Generate", "Regenerate"],  # Include both
            "confirm_button_text": "Yes, regenerate",    # Only needed for Regenerate
            "credentials": {
                "consumer_key": 'xpath=//button[@aria-label="Copy API Key to clipboard"]/preceding-sibling::p[@data-testid="credential-information-credential"]',
                "consumer_secret": 'xpath=//button[@aria-label="Copy API Key Secret to clipboard"]/preceding-sibling::p[@data-testid="credential-information-credential"]'
            }
        },
        "Bearer Token": {
            "panel_text": "Bearer Token",
            "save_button_text": "Yes, I saved it",
            "button_texts": ["Generate", "Regenerate"],  # Include both
            "confirm_button_text": "Yes, regenerate",    # Only needed for Regenerate
            "credentials": {
                "bearer_token": 'xpath=//button[@aria-label="Copy Bearer Token to clipboard"]/preceding-sibling::p[@data-testid="credential-information-credential"]'
            }
        },
        "Access Token and Secret": {
            "panel_text": "Access Token and Secret",
            "save_button_text": "Yes, I saved them",
            "button_texts": ["Generate", "Regenerate"],  # Include both
            "confirm_button_text": "Yes, regenerate",    # Only needed for Regenerate
            "credentials": {
                "access_token": 'xpath=//button[@aria-label="Copy Access Token to clipboard"]/preceding-sibling::p[@data-testid="credential-information-credential"]',
                "access_token_secret": 'xpath=//button[@aria-label="Copy Access Token Secret to clipboard"]/preceding-sibling::p[@data-testid="credential-information-credential"]'
            }
        }
    }

    def __init__(self, account_no: str):
        self.account_no = account_no
        self.account_data = None
        self.current_proxy = None
        self.user_agent = None  # Initialize this

    # =========================
    # Helper Methods
    # =========================

    async def wait_and_click(self, page, selector: str, timeout: int = 5000, delay: float = 0.5):
        """Helper method to wait for element and click with retry logic."""
        try:
            element = await page.wait_for_selector(selector, timeout=timeout)
            await asyncio.sleep(delay)
            await element.click()
            logger.debug(f"Clicked element '{selector}'")
            return True
        except Exception as e:
            logger.error(f"Error clicking element '{selector}': {str(e)}")
            return False

    async def check_account_status(self, page) -> str:
        """
        Checks the account status on the developer dashboard.
        Returns one of: 'suspended', 'unauthorized', 'Needs Verification', 'Active'
        """
        try:
            # Check for suspension or locked account
            suspension_selector = 'h6[data-testid="unhealthy-callout-header"]'
            suspension = await page.query_selector(suspension_selector)
            if suspension:
                text = await suspension.text_content()
                if "Your X account is suspended" in text or "Your Twitter account is suspended" in text:
                    return "suspended"
                elif "Your X account is locked" in text or "Your Twitter account is locked" in text:
                    return "Needs Verification"

            # Check for redirection URLs
            current_url = page.url
            if current_url.startswith("https://x.com/i/flow/login") or current_url.startswith("https://twitter.com/i/flow/login"):
                return "unauthorized"
            elif current_url.startswith("https://x.com/account/access") or current_url.startswith("https://twitter.com/account/access"):
                return "Needs Verification"

            return "Active"
        except Exception as e:
            logger.error(f"Error checking account status: {str(e)}", exc_info=True)
            return "Unknown"


    async def fill_form_field(self, page, selector: str, value: str):
        """Fills a form field with the given value."""
        try:
            field = await page.wait_for_selector(selector, timeout=5000)
            await field.fill(value)
            logger.debug(f"Filled form field '{selector}' with value: {value}")
        except Exception as e:
            logger.error(f"Error filling form field '{selector}': {str(e)}", exc_info=True)

    async def get_text_content(self, page, selector: str, timeout: int = 5000) -> Optional[str]:
        """
        Extracts text content from a specified selector without waiting for changes.
        Waits until the text content is non-empty.
        """
        try:
            end_time = datetime.now().timestamp() + (timeout / 1000)
            while datetime.now().timestamp() < end_time:
                element = await page.query_selector(selector)
                if element:
                    text = await element.text_content()
                    text = text.strip() if text else ""
                    if text:
                        logger.debug(f"Extracted text from '{selector}': {text}")
                        return text
                await asyncio.sleep(1)  # Wait a second before retrying
            logger.error(f"Timeout waiting for non-empty text in selector '{selector}'")
            return None
        except Exception as e:
            logger.error(f"Error extracting text from '{selector}': {str(e)}", exc_info=True)
            return None

    async def extract_credential(self, page, credential_name: str) -> Optional[Dict[str, str]]:
        """Extracts the credential(s) based on the credential name."""
        try:
            info = self.credential_info.get(credential_name)
            if not info:
                logger.error(f"No info defined for '{credential_name}'")
                return None

            credentials = {}

            if credential_name == "Client ID":
                # Extract Client ID directly without waiting for text to change
                value = await self.get_text_content(page, info["value_selector"])
                if value:
                    credentials["client_id"] = value
                    logger.debug(f"Extracted 'client_id': {value}")
                else:
                    logger.error("Failed to extract 'client_id'")
                    return None
                return credentials

            # Find the panel based on panel_text
            panel_selector = f'div.index__TokenInfoPanel--3vyPY:has(div.index__tokenType--2IFoe:has-text("{info["panel_text"]}"))'
            panel = await page.query_selector(panel_selector)
            if not panel:
                logger.error(f"Panel for '{credential_name}' not found")
                # Capture page content for debugging
                page_content = await page.content()
                async with aiofiles.open(os.path.join(OUTPUT_FOLDER, f"missing_panel_{credential_name}_{self.account_no}.html"), 'w', encoding='utf-8') as f:
                    await f.write(page_content)
                logger.debug(f"Page content saved for debugging: missing_panel_{credential_name}_{self.account_no}.html")
                return None
            else:
                logger.debug(f"Panel for '{credential_name}' found")

            # Handle multiple possible button texts
            button_texts = info.get("button_texts", ["Regenerate"])
            main_button = None
            clicked_button_text = None  # Track which button was clicked
            for text in button_texts:
                button_selector = f'button:has-text("{text}")'
                main_button = await panel.query_selector(button_selector)
                if main_button and await main_button.is_visible() and await main_button.is_enabled():
                    await main_button.click()
                    logger.debug(f"Clicked '{text}' button for '{credential_name}'")
                    await asyncio.sleep(2)
                    clicked_button_text = text
                    break
            if not main_button:
                logger.error(f"Neither 'Regenerate' nor 'Generate' button found for '{credential_name}'")
                # Capture screenshot for debugging
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_path = os.path.join(OUTPUT_FOLDER, f"regenerate_error_{credential_name}_{self.account_no}_{timestamp}.png")
                await page.screenshot(path=screenshot_path)
                logger.debug(f"Screenshot for missing '{credential_name}' button saved to {screenshot_path}")
                return None

            # Conditionally handle confirmation based on button clicked
            confirm_button_text = info.get("confirm_button_text")
            if confirm_button_text and clicked_button_text in ["Regenerate", "Generate"]:
                # Attempt to click "Yes, regenerate" if it appears
                confirm_button_selector = f'button:has-text("{confirm_button_text}")'
                confirmation_present = await page.query_selector(confirm_button_selector)
                if confirmation_present:
                    await self.wait_and_click(page, confirm_button_selector)
                    logger.debug(f"Clicked '{confirm_button_text}' button for '{credential_name}'")
                    await asyncio.sleep(3)
                else:
                    logger.debug(f"No confirmation needed after clicking '{clicked_button_text}' for '{credential_name}'")

            # Extract credential values
            for key, value_selector in info["credentials"].items():
                value = await self.get_text_content(page, value_selector)
                if value:
                    credentials[key] = value
                    logger.debug(f"Extracted '{key}': {value}")
                else:
                    logger.error(f"Failed to extract '{key}'")
                    # Capture screenshot for debugging
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    screenshot_path = os.path.join(OUTPUT_FOLDER, f"missing_credential_{key}_{self.account_no}_{timestamp}.png")
                    await page.screenshot(path=screenshot_path)
                    logger.debug(f"Screenshot for missing credential '{key}' saved to {screenshot_path}")
                    return None

            # Click Save button and ensure it's enabled
            save_button_selector = f'button:has-text("{info["save_button_text"]}")'
            # Wait until the save button is enabled
            try:
                await page.wait_for_selector(save_button_selector + ":enabled", timeout=5000)
                await self.wait_and_click(page, save_button_selector)
                await asyncio.sleep(2)
                logger.debug(f"Clicked '{info['save_button_text']}' button for '{credential_name}'")
            except PlaywrightTimeoutError:
                logger.error(f"Save button '{info['save_button_text']}' not enabled for '{credential_name}'")
                # Capture screenshot for debugging
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_path = os.path.join(OUTPUT_FOLDER, f"save_button_error_{credential_name}_{self.account_no}_{timestamp}.png")
                await page.screenshot(path=screenshot_path)
                logger.debug(f"Screenshot for save button error saved to {screenshot_path}")
                return None

            return credentials
        except Exception as e:
            logger.error("Error extracting creds")
            return None

    async def setup_browser_context(self, account_data: Dict) -> Optional[Tuple[Playwright, any, any]]:

        """Sets up the browser context with proxy and authentication based on account data."""
        try:
            # Extract proxy details from account_data
            proxy_url = account_data.get('proxy_url')
            proxy_port = account_data.get('proxy_port')
            proxy_username = account_data.get('proxy_username')
            proxy_password = account_data.get('proxy_password')

            if not all([proxy_url, proxy_port, proxy_username, proxy_password]):
                logger.error(f"Proxy details missing for account {self.account_no}. Skipping browser setup.")
                return None

            # Construct proxy configuration
            proxy_config = {
                'server': f"http://{proxy_url}:{proxy_port}",
                'username': proxy_username,
                'password': proxy_password
            }

            # Initialize playwright
            p = await async_playwright().start()

            # Launch browser with proxy configuration
            browser = await p.chromium.launch(
                headless=True,  # Set to True for production
                proxy=proxy_config,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu',
                    '--window-size=1280,800'
                ]
            )

            # Create new context with custom settings
            context = await browser.new_context(
                user_agent=account_data.get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'),
                viewport={'width': 1280, 'height': 800},
                ignore_https_errors=True,
                java_script_enabled=True,
                bypass_csp=True
            )

            # Set timeouts
            context.set_default_navigation_timeout(BROWSER_TIMEOUT)
            context.set_default_timeout(PAGE_TIMEOUT)

            # Add authentication cookies if available
            if account_data.get('ct0') and account_data.get('auth_token'):
                await context.add_cookies([
                    {
                        'name': 'ct0',
                        'value': account_data['ct0'],
                        'domain': '.twitter.com',
                        'path': '/',
                        'secure': True,
                        'sameSite': 'Lax'
                    },
                    {
                        'name': 'auth_token',
                        'value': account_data['auth_token'],
                        'domain': '.twitter.com',
                        'path': '/',
                        'secure': True,
                        'sameSite': 'Lax'
                    }
                ])

            return p, browser, context

        except Exception as e:
            logger.error(f"Error setting up browser context: {str(e)}")
            return None

    async def change_language_to_english(self, context) -> bool:
        """Changes Twitter interface language to English."""
        try:
            page = await context.new_page()
            await page.goto('https://twitter.com/settings/language', timeout=60000)
            await asyncio.sleep(3)

            # Check for account status
            current_url = page.url
            if current_url.startswith("https://x.com/i/flow/login") or current_url.startswith("https://twitter.com/i/flow/login"):
                self.account_data['account_status'] = "unauthorized"
                logger.info(f"Account {self.account_no} is unauthorized.")
                await page.close()
                return False
            elif current_url.startswith("https://x.com/account/access") or current_url.startswith("https://twitter.com/account/access"):
                self.account_data['account_status'] = "Needs Verification"
                logger.info(f"Account {self.account_no} needs verification.")
                await page.close()
                return False
            else:
                self.account_data['account_status'] = "Active"

            # Check if language is already English
            current_language = await self.get_text_content(page, 'select[name="user[language]"] option:checked')
            if current_language and current_language.lower() == "english":
                logger.info("Language is already set to English. Skipping language change.")
                self.account_data['language_status'] = 'Already English'
                await page.close()
                return True

            # Wait for the language dropdown
            dropdown_selector = 'select[name="user[language]"]'
            try:
                await page.wait_for_selector(dropdown_selector, timeout=5000)
            except PlaywrightTimeoutError:
                logger.error("Language dropdown not found. Skipping language change.")
                self.account_data['language_status'] = 'Failed'
                await page.close()
                return False

            # Select English option
            await page.select_option(dropdown_selector, 'en')
            await asyncio.sleep(2)

            # Wait for the save button to be enabled
            save_button_selector = 'div[data-testid="Settings_Save_Button"]'
            try:
                await page.wait_for_selector(save_button_selector + ":enabled", timeout=5000)
            except PlaywrightTimeoutError:
                logger.info("Save button is not active, likely already in English.")
                self.account_data['language_status'] = 'Already English'
                await page.close()
                return True

            # Click save button
            await self.wait_and_click(page, save_button_selector)
            await asyncio.sleep(3)

            logger.info("Language changed to English successfully")
            self.account_data['language_status'] = 'Success'
            await page.close()
            return True

        except PlaywrightTimeoutError as e:
            logger.error(f"Timeout while changing language: {str(e)}", exc_info=True)
            self.account_data['language_status'] = 'Failed'
            return False
        except Exception as e:
            logger.error(f"Error changing language: {str(e)}", exc_info=True)
            # Take error screenshot
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = os.path.join(OUTPUT_FOLDER, f"language_error_{self.account_no}_{timestamp}.png")
            try:
                await page.screenshot(path=screenshot_path)
                logger.debug(f"Error screenshot saved to {screenshot_path}")
            except Exception as screenshot_error:
                logger.error(f"Failed to take screenshot: {str(screenshot_error)}")
            self.account_data['language_status'] = 'Failed'
            await page.close()
            return False

    async def get_credentials_from_existing_app(self, page) -> Optional[Dict[str, str]]:
        """Gets credentials from an existing app setup by directly extracting text."""
        try:
            # Navigate directly to Keys and Tokens
            logger.info("Accessing Keys and Tokens tab...")
            await self.wait_and_click(page, 'button[role="tab"]:has-text("Keys and tokens")')
            await asyncio.sleep(3)

            credentials = {}

            # Extract Client ID
            client_id_data = await self.extract_credential(page, "Client ID")
            if client_id_data:
                credentials.update(client_id_data)
            else:
                logger.error("Failed to extract Client ID")
                return None

            # Extract Client Secret
            client_secret_data = await self.extract_credential(page, "Client Secret")
            if client_secret_data:
                credentials.update(client_secret_data)
            else:
                logger.error("Failed to extract Client Secret")
                return None

            # Extract API Key and Secret
            api_credentials = await self.extract_credential(page, "API Key and Secret")
            if api_credentials:
                credentials.update(api_credentials)
            else:
                logger.error("Failed to extract API Key and Secret")
                return None

            # Extract Bearer Token
            bearer_token_data = await self.extract_credential(page, "Bearer Token")
            if bearer_token_data:
                credentials.update(bearer_token_data)
            else:
                logger.error("Failed to extract Bearer Token")
                return None

            # Extract Access Token and Secret
            access_token_data = await self.extract_credential(page, "Access Token and Secret")
            if access_token_data:
                credentials.update(access_token_data)
            else:
                logger.error("Failed to extract Access Token and Secret")
                return None

            # Verify all credentials were obtained
            expected_keys = [
                "client_id",
                "client_secret",
                "consumer_key",
                "consumer_secret",
                "bearer_token",
                "access_token",
                "access_token_secret"
            ]
            missing = [k for k in expected_keys if k not in credentials]
            if missing:
                raise Exception(f"Missing credentials: {', '.join(missing)}")

            logger.info("Successfully obtained all credentials from existing app")
            return credentials

        except Exception as e:
            logger.error(f"Error getting credentials from existing app: {str(e)}", exc_info=True)
            return None

    async def get_developer_credentials(self) -> Optional[Dict[str, str]]:
        """Gets developer credentials from Twitter Developer Portal."""
        try:
            setup = await self.setup_browser_context(self.account_data)
            if not setup:
                return None
            playwright, browser, context = setup

            try:
                page = await context.new_page()
                await page.goto('https://developer.twitter.com/en/portal/dashboard', timeout=10000)
                await asyncio.sleep(3)

                # Check account status
                status = await self.check_account_status(page)
                if status in ["suspended", "unauthorized", "Needs Verification"]:
                    self.account_data['developer_status'] = status
                    logger.info(f"Account {self.account_no} status is '{status}'. Skipping developer credentials extraction.")
                    await browser.close()
                    await playwright.stop()
                    return None
                else:
                    self.account_data['developer_status'] = "Active"

                # Navigate through developer portal
                logger.debug("Setting up developer credentials...")

                # Check for signup button
                try:
                    signup_button = await page.wait_for_selector("text='Sign up for Free Account'", timeout=5000)
                    if signup_button:
                        logger.info("New account setup required...")
                        await self.wait_and_click(page, "text='Sign up for Free Account'")
                        await asyncio.sleep(2)

                        # Fill in use case description with GPT-4 generated text
                        logger.debug("Filling in use case description...")
                        generated_text = generate_text_with_gpt4()
                        if not generated_text:
                            logger.error("Failed to generate use case description.")
                            return None
                        textarea = await page.wait_for_selector('textarea')
                        await textarea.fill(generated_text)
                        await asyncio.sleep(random.uniform(3, 5))

                        # Accept terms
                        for checkbox_selector in [
                            'input[name="resellTerms"]', 
                            'input[name="voilationTerms"]', 
                            'input[name="acceptedTerms"]'
                        ]:
                            await self.wait_and_click(page, checkbox_selector)
                            await asyncio.sleep(1)

                        # Submit the form
                        await self.wait_and_click(page, 'span:has-text("Submit")')
                        await asyncio.sleep(5)

                except PlaywrightTimeoutError:
                    logger.info("No signup button found, assuming already registered")

                # Navigate to Projects & Apps in both cases
                logger.info("Navigating to Projects & Apps...")
                await self.wait_and_click(page, 'span:has-text("Projects & Apps")')
                await asyncio.sleep(3)

                # Try to find standalone app button
                standalone_app_selector = 'button.index__navItemButton--17Psw.index__isStandaloneApp--3NaIM'
                try:
                    await page.wait_for_selector(standalone_app_selector, timeout=5000)
                    await self.wait_and_click(page, standalone_app_selector)
                    await asyncio.sleep(2)
                    logger.info("Standalone app found and clicked.")
                except PlaywrightTimeoutError:
                    logger.info("No standalone app found, continuing with default app.")

                # Click settings icon (cog)
                settings_cog_selector = 'span.Icon.Icon--cog[data-feather-tooltip-target]'
                await self.wait_and_click(page, settings_cog_selector)
                await asyncio.sleep(2)
                
                # Check if app needs setup or is already configured
                edit_button_selector = 'span.Icon.Icon--editPencil.index__panelPencilIcon--19A1v'
                edit_button = await page.query_selector(edit_button_selector)
                if not edit_button:
                    logger.info("Setting up new app...")
                    await self.wait_and_click(page, 'span:has-text("Set up")')
                    await asyncio.sleep(2)
                    
                    # Set permissions
                    await self.wait_and_click(page, 'input[name="accessLevel"][value="READ_WRITE_DM"]')
                    await self.wait_and_click(page, 'input[name="appType"][value="WebApp"]')
                    await asyncio.sleep(1)
                    
                    # Fill URLs
                    await self.fill_form_field(page, 'input[data-testid="callback-url-input"]', 'https://twitter.com')
                    await self.fill_form_field(page, 'input[data-testid="website-url-input"]', 'https://twitter.com')
                    await asyncio.sleep(1)
                    
                    # Save and confirm
                    await self.wait_and_click(page, 'span:has-text("Save")')
                    await self.wait_and_click(page, 'span:has-text("Yes")')
                    await asyncio.sleep(3)
                    
                    # Click "Done" button
                    logger.info("Clicking 'Done' button...")
                    done_button_selector = 'button[data-testid="done-button-oauth-2-keys-and-tokens"]'
                    if not await self.wait_and_click(page, done_button_selector):
                        logger.error("Failed to click 'Done' button")
                        return None
                    await asyncio.sleep(2)

                    # Click "Yes, I saved it" button
                    logger.info("Clicking 'Yes, I saved it' button...")
                    saved_it_button_selector = 'button:has-text("Yes, I saved it")'
                    if not await self.wait_and_click(page, saved_it_button_selector):
                        logger.error("Failed to click 'Yes, I saved it' button")
                        return None
                    await asyncio.sleep(2)

                    # Extract credentials
                    credentials = await self.get_credentials_from_existing_app(page)
                    if not credentials:
                        logger.error("Failed to obtain credentials after app setup")
                        return None
                    
                    # Update account_data with the new credentials
                    for key in [
                        "client_id", "client_secret", "consumer_key", "consumer_secret",
                        "bearer_token", "access_token", "access_token_secret"
                    ]:
                        if key in credentials:
                            self.account_data[key] = credentials[key]
                    logger.info("Successfully obtained and stored all credentials")
                    return credentials

                else:
                    logger.info("Found existing app setup...")
                    # Extract credentials from existing app
                    credentials = await self.get_credentials_from_existing_app(page)
                    if credentials:
                        # Update account_data with the new credentials
                        for key in [
                            "client_id", "client_secret", "consumer_key", "consumer_secret",
                            "bearer_token", "access_token", "access_token_secret"
                        ]:
                            if key in credentials:
                                self.account_data[key] = credentials[key]
                        logger.info("Successfully obtained and stored all credentials")
                    return credentials

            except Exception as e:
                logger.error(f"Error in developer portal: {str(e)}", exc_info=True)
                # Take screenshot for debugging
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_path = os.path.join(OUTPUT_FOLDER, f"error_{self.account_no}_{timestamp}.png")
                try:
                    await page.screenshot(path=screenshot_path)
                    logger.debug(f"Error screenshot saved to {screenshot_path}")
                except Exception as screenshot_error:
                    logger.error(f"Failed to take screenshot: {str(screenshot_error)}")
                return None

            finally:
                await browser.close()
                await playwright.stop()
        except Exception as e:
            logger.error("Error extracting creds1")
            return None


async def load_account_data_from_csv(account_no: str) -> Optional[Dict]:
    """Load account data for a specific account_no from the CSV."""
    try:
        # Read CSV using pandas
        df = pd.read_csv(ACCOUNTS_FILE)
        
        # Find the account
        account = df[df['account_no'] == account_no]
        
        if account.empty:
            logger.error(f"Account {account_no} not found in {ACCOUNTS_FILE}")
            return None
            
        # Convert the row to dictionary
        account_data = account.iloc[0].to_dict()
        
        # Convert any numpy types to python native types
        account_data = {k: v.item() if hasattr(v, 'item') else v for k, v in account_data.items()}
        
        return account_data
        
    except Exception as e:
        logger.error(f"Error loading account data: {str(e)}", exc_info=True)
        return None

async def save_account_data_to_csv(account_no: str, updated_data: Dict) -> bool:
    """Save the updated account data back to the CSV file."""
    try:
        async with csv_lock:
            # Read CSV using pandas
            df = pd.read_csv(ACCOUNTS_FILE)
            
            # Update the account data
            mask = df['account_no'] == account_no
            if not mask.any():
                logger.error(f"Account {account_no} not found in CSV")
                return False
            
            # Update all columns that exist in the DataFrame
            for col, value in updated_data.items():
                if col in df.columns:
                    df.loc[mask, col] = value
            
            # Create backup
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = f"{ACCOUNTS_FILE}.{timestamp}.bak"
            df.to_csv(backup_file, index=False)
            logger.info(f"Created backup at {backup_file}")
            
            # Save updated CSV
            df.to_csv(ACCOUNTS_FILE, index=False)
            
            logger.info(f"Account {account_no}: Data saved successfully")
            return True

    except Exception as e:
        logger.error(f"Error saving account data: {str(e)}", exc_info=True)
        return False
    # =========================
    # TwitterAccountManager Class (Continued)
    # =========================

    #async def setup_browser_context(self, account_data: Dict) -> Optional[Tuple[async_playwright.Playwright, any, any]]:
    
    # =========================
    # Main Execution Flow
    # =========================

async def process_account(account_no: str):
    """Process a single account: change language and extract developer credentials."""
    manager = TwitterAccountManager(account_no)
    
    # Load account data
    account_data = await load_account_data_from_csv(account_no)
    if not account_data:
        logger.error(f"Account {account_no}: Data not found.")
        return
    
    manager.account_data = account_data

    # Extract proxy details from account_data
    proxy_url = account_data.get('proxy_url')
    proxy_port = account_data.get('proxy_port')
    proxy_username = account_data.get('proxy_username')
    proxy_password = account_data.get('proxy_password')

    if not all([proxy_url, proxy_port, proxy_username, proxy_password]):
        logger.error(f"Account {account_no}: Missing proxy details.")
        # Update account status as failed
        manager.account_data.update({
            'language_status': 'Failed',
            'developer_status': 'Failed',
            'account_status': 'Failed'
        })
        await save_account_data_to_csv(account_no, manager.account_data)
        return

    # Change language to English
    try:
        playwright, browser, context = await manager.setup_browser_context(account_data)
        if not all([playwright, browser, context]):
            manager.account_data.update({
                'language_status': 'Failed',
                'developer_status': 'Failed',
                'account_status': 'Failed'
            })
            await save_account_data_to_csv(account_no, manager.account_data)
            return

        # language_changed = await manager.change_language_to_english(context)
        # if not language_changed:
        #     logger.error(f"Account {account_no}: Failed to change language to English.")
        # else:
        #     logger.info(f"Account {account_no}: Language changed to English successfully.")

        # Extract developer credentials
        credentials = await manager.get_developer_credentials()
        if credentials:
            logger.info(f"Account {account_no}: Developer credentials extracted successfully.")
        else:
            logger.error(f"Account {account_no}: Failed to extract developer credentials.")

        # Save updated account data
        await save_account_data_to_csv(account_no, manager.account_data)

    except Exception as e:
        logger.error(f"Account {account_no}: Exception occurred - {str(e)}", exc_info=True)
        # Update account status as failed
        manager.account_data.update({
            'language_status': 'Failed',
            'developer_status': 'Failed',
            'account_status': 'Failed'
        })
        await save_account_data_to_csv(account_no, manager.account_data)

async def process_accounts(max_concurrent: int = 4):
    """Process multiple accounts concurrently."""
    try:
        df = pd.read_csv(ACCOUNTS_FILE)
        total_accounts = len(df)
        logger.info(f"Found {total_accounts} accounts to process.")

        semaphore = asyncio.Semaphore(max_concurrent)

        async def sem_task(account_no: str):
            async with semaphore:
                await process_account(account_no)

        tasks = [sem_task(row['account_no']) for _, row in df.iterrows()]
        await asyncio.gather(*tasks)

        logger.info("All accounts have been processed.")

    except Exception as e:
        logger.error(f"Error in process_accounts: {str(e)}", exc_info=True)

async def main():
    """Main function to handle command-line arguments and initiate processing."""
    if len(sys.argv) == 2:
        # Single account mode
        account_no = sys.argv[1]
        logger.info(f"Processing single account: {account_no}")
        await process_account(account_no)
    else:
        # Batch mode - process all accounts
        await process_accounts(max_concurrent=MAX_CONCURRENT_TASKS)

if __name__ == "__main__":
    asyncio.run(main())
