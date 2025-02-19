import logging
import asyncio
import json
import os
import signal
import psutil
from typing import Optional, Dict
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, TimeoutError

logger = logging.getLogger(__name__)

class BrowserManager:
    """Singleton to manage browser instances"""
    _instances: Dict[str, 'BrowserLauncher'] = {}
    
    @classmethod
    def get_instance(cls, account_id: str) -> Optional['BrowserLauncher']:
        """Get browser instance for account"""
        return cls._instances.get(account_id)
    
    @classmethod
    def set_instance(cls, account_id: str, instance: 'BrowserLauncher'):
        """Store browser instance for account"""
        cls._instances[account_id] = instance
    
    @classmethod
    def remove_instance(cls, account_id: str):
        """Remove browser instance for account"""
        if account_id in cls._instances:
            del cls._instances[account_id]
    
    @classmethod
    async def cleanup_all(cls):
        """Close all browser instances"""
        for instance in cls._instances.values():
            await instance.close()
        cls._instances.clear()

class BrowserLauncher:
    def __init__(self, account_id: str):
        self.account_id = account_id
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.browser_pid = None
        self.child_pids = []
        self.max_retries = 3
        self.base_timeout = 120000  # 120 seconds base timeout
        self.retry_delay = 10  # 10 seconds between retries

    async def _wait_for_page_load(self, timeout: int = 120000) -> bool:
        """Wait for page to load with multiple selectors"""
        try:
            # Try different selectors that indicate page load
            selectors = [
                '[data-testid="primaryColumn"]',  # Main timeline
                '[aria-label="Home timeline"]',   # Alternative timeline
                '[data-testid="AppTabBar_Home_Link"]',  # Home tab
                'article[data-testid]',  # Any tweet
                '[data-testid="SideNav"]'  # Side navigation
            ]
            
            for selector in selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=20000)  # 20 seconds per selector
                    logger.info(f"Page loaded successfully with selector: {selector}")
                    return True
                except TimeoutError:
                    continue
            
            # If no selectors found, try one last time with longer timeout
            await self.page.wait_for_selector('[data-testid="primaryColumn"]', timeout=timeout)
            return True
            
        except Exception as e:
            logger.error(f"Error waiting for page load: {str(e)}")
            return False

    async def launch(
        self,
        auth_token: str,
        ct0: str,
        proxy_config: Dict,
        user_agent: str
    ) -> bool:
        """Launch browser with account configuration"""
        retry_count = 0
        last_error = None
        
        while retry_count < self.max_retries:
            try:
                timeout = self.base_timeout * (retry_count + 1)  # Increase timeout with each retry
                logger.info(f"Launching browser for account {self.account_id} (Attempt {retry_count + 1}/{self.max_retries})")
                
                # Format proxy URL with credentials
                proxy_url = f"http://{proxy_config['username']}:{proxy_config['password']}@{proxy_config['host']}:{proxy_config['port']}"
                
                # Initialize playwright
                self.playwright = await async_playwright().start()
                
                # Launch browser with proxy
                self.browser = await self.playwright.chromium.launch(
                    proxy={
                        "server": proxy_url,
                        "username": proxy_config['username'],
                        "password": proxy_config['password']
                    },
                    headless=False,  # Run in headful mode
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-features=IsolateOrigins,site-per-process',
                        '--disable-site-isolation-trials',
                        '--window-size=1280,800',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage'
                    ]
                )

                # Store browser process ID and child processes
                try:
                    browser_process = psutil.Process(self.browser.process.pid)
                    self.browser_pid = browser_process.pid
                    self.child_pids = [child.pid for child in browser_process.children(recursive=True)]
                    logger.info(f"Browser process ID: {self.browser_pid}")
                    logger.info(f"Child process IDs: {self.child_pids}")
                except Exception as e:
                    logger.error(f"Error getting browser PIDs: {str(e)}")
                
                # Create context with authentication
                self.context = await self.browser.new_context(
                    user_agent=user_agent,
                    viewport={'width': 1280, 'height': 800},
                    ignore_https_errors=True,
                    bypass_csp=True,
                    proxy={
                        "server": proxy_url,
                        "username": proxy_config['username'],
                        "password": proxy_config['password']
                    }
                )
                
                # Add required cookies
                await self.context.add_cookies([
                    {
                        'name': 'auth_token',
                        'value': auth_token,
                        'domain': '.twitter.com',
                        'path': '/'
                    },
                    {
                        'name': 'ct0',
                        'value': ct0,
                        'domain': '.twitter.com',
                        'path': '/'
                    }
                ])
                
                # Create new page
                self.page = await self.context.new_page()
                
                # Add scripts to avoid detection
                await self.page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    
                    window.chrome = {
                        runtime: {}
                    };
                    
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });
                    
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['en-US', 'en']
                    });
                    
                    // Add more realistic navigator properties
                    Object.defineProperty(navigator, 'deviceMemory', {
                        get: () => 8
                    });
                    
                    Object.defineProperty(navigator, 'hardwareConcurrency', {
                        get: () => 8
                    });
                    
                    Object.defineProperty(navigator, 'platform', {
                        get: () => 'MacIntel'
                    });
                    
                    // Add WebGL fingerprinting evasion
                    const getParameter = WebGLRenderingContext.prototype.getParameter;
                    WebGLRenderingContext.prototype.getParameter = function(parameter) {
                        if (parameter === 37445) {
                            return 'Intel Inc.'
                        }
                        if (parameter === 37446) {
                            return 'Intel Iris OpenGL Engine'
                        }
                        return getParameter.apply(this, arguments);
                    };
                """)
                
                # Navigate to Twitter with retry
                for attempt in range(3):
                    try:
                        await self.page.goto('https://twitter.com/home', timeout=timeout)
                        break
                    except TimeoutError:
                        if attempt == 2:  # Last attempt
                            raise
                        logger.warning(f"Navigation timeout, retrying... (Attempt {attempt + 1}/3)")
                        await asyncio.sleep(5)  # 5 seconds between retries
                
                # Wait for page load with extended timeout
                if await self._wait_for_page_load(timeout=timeout):
                    logger.info(f"Successfully loaded Twitter home page for account {self.account_id}")
                    
                    # Store instance in manager
                    BrowserManager.set_instance(self.account_id, self)
                    
                    return True
                else:
                    raise TimeoutError("Failed to detect page load")

            except Exception as e:
                last_error = e
                logger.error(f"Failed to launch browser for account {self.account_id} (Attempt {retry_count + 1}/{self.max_retries}): {str(e)}")
                await self.close()
                
                if retry_count < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                    retry_count += 1
                else:
                    break

        logger.error(f"Failed to launch browser for account {self.account_id} after {self.max_retries} attempts: {str(last_error)}")
        return False

    async def close(self):
        """Close browser and cleanup"""
        try:
            # First try graceful shutdown
            if self.page:
                try:
                    await self.page.close()
                except:
                    pass
                self.page = None
            
            if self.context:
                try:
                    await self.context.close()
                except:
                    pass
                self.context = None
            
            if self.browser:
                try:
                    await self.browser.close()
                except:
                    pass
                self.browser = None
                
            if self.playwright:
                try:
                    await self.playwright.stop()
                except:
                    pass
                self.playwright = None

            # Force kill browser process and children
            if self.browser_pid:
                try:
                    # Kill child processes first
                    for pid in self.child_pids:
                        try:
                            process = psutil.Process(pid)
                            process.kill()
                            logger.info(f"Killed child process {pid}")
                        except psutil.NoSuchProcess:
                            pass
                        except Exception as e:
                            logger.error(f"Error killing child process {pid}: {str(e)}")
                    
                    # Kill parent process
                    try:
                        parent = psutil.Process(self.browser_pid)
                        parent.kill()
                        logger.info(f"Killed parent process {self.browser_pid}")
                    except psutil.NoSuchProcess:
                        pass
                    except Exception as e:
                        logger.error(f"Error killing parent process: {str(e)}")
                    
                    # Find and kill any remaining chromium processes for this account
                    chrome_process_names = [
                        'chrome',
                        'chromium',
                        'chrome-renderer',
                        'chrome-gpu',
                        'chrome-crashpad',
                        'chrome-sandbox',
                        'chrome-helper',
                        'Google Chrome',
                        'Chromium'
                    ]
                    
                    chrome_paths = [
                        '/Applications/Google Chrome.app',
                        '/Applications/Chromium.app',
                        '/usr/bin/chromium',
                        '/usr/bin/chromium-browser',
                        '/usr/bin/google-chrome'
                    ]
                    
                    current_user = os.getlogin()
                    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'username', 'exe']):
                        try:
                            # Skip if not our user
                            if proc.info['username'] != current_user:
                                continue
                                
                            is_chrome = False
                            # Check process name
                            if proc.info['name'] and any(name.lower() in proc.info['name'].lower() for name in chrome_process_names):
                                is_chrome = True
                                
                            # Check executable path
                            if proc.info['exe'] and any(path in proc.info['exe'] for path in chrome_paths):
                                is_chrome = True
                                
                            if is_chrome:
                                # Check command line for account ID
                                cmdline = proc.info['cmdline']
                                if cmdline and any(self.account_id in arg for arg in cmdline):
                                    proc.kill()
                                    logger.info(f"Killed remaining chrome process {proc.info['pid']} ({proc.info['name']})")
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                        except Exception as e:
                            logger.error(f"Error checking process: {str(e)}")
                        
                except Exception as e:
                    logger.error(f"Error force killing processes: {str(e)}")
                
                self.browser_pid = None
                self.child_pids = []
            
            # Remove from manager
            BrowserManager.remove_instance(self.account_id)
                
        except Exception as e:
            logger.error(f"Error closing browser for account {self.account_id}: {str(e)}")

    async def is_alive(self) -> bool:
        """Check if browser session is still active"""
        try:
            if not all([self.browser, self.context, self.page]):
                return False
            
            # Try to access Twitter
            await self.page.goto('https://twitter.com/home', timeout=60000)  # 60 second timeout
            return await self._wait_for_page_load(timeout=60000)  # 60 second timeout
        except:
            return False
