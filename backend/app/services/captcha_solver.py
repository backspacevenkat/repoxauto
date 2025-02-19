import logging
import os
import json
import re
import time
import asyncio
import traceback
from datetime import datetime
from urllib.parse import parse_qs, urlparse, unquote, quote
from playwright.async_api import Page, Response
from twocaptcha import TwoCaptcha
import httpx

# Configure logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler('logs/captcha_solver.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class CaptchaSolver:
    def __init__(self, proxy_config):
        self.proxy_config = proxy_config
        self.logger = logging.getLogger(__name__)
        
        # Updated PUBLIC_KEY to match payload
        self.PUBLIC_KEY = "0152B4EB-D2DC-460A-89A1-629838B529C9" 
        self.TWO_CAPTCHA_KEY = '4a5a819b86f4644d2fc770f53bdc40bc'
        
        # State tracking
        self.data_blob = None
        self.page = None
        self._last_frame = None
        self.session_token = None
        self.game_token = None
        
        # Initialize solver with longer timeout
        self.solver_2captcha = TwoCaptcha(self.TWO_CAPTCHA_KEY)
        self.solver_2captcha.timeout = 900  # 15 minute timeout

        # Default user agent
        self.user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    
    async def setup_page_handlers(self, page):
        """Set up all necessary page handlers with enhanced error catching."""
        try:
            self.page = page
            
            # Setup request interception
            await page.route("**/*", self.handle_request)
            
            # Setup response handling
            page.on("response", self.handle_response)
            
            # Setup frame tracking with enhanced initialization
            page.on("framenavigated", self.handle_frame)
            page.on("frameattached", lambda frame: self.logger.info(f"Frame attached: {frame.url}"))
            page.on("framedetached", lambda frame: self.logger.info(f"Frame detached: {frame.url}"))
            
            # Handle console messages
            page.on("console", self.handle_console_message)
            
            # Wait for any existing frames to load
            for frame in page.frames:
                if 'arkoselabs' in frame.url:
                    try:
                        await frame.wait_for_load_state('domcontentloaded', timeout=10000)
                        self.logger.info(f"Existing frame loaded: {frame.url}")
                    except Exception as e:
                        self.logger.error(f"Error loading existing frame: {e}")
            
            # Enhanced WebSocket and data capture monitoring with frame support
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
            
            if self.PUBLIC_KEY in url and method == 'POST':
                post_data = request.post_data
                if post_data:
                    try:
                        if isinstance(post_data, str):
                            params = parse_qs(post_data)
                            blob_list = params.get('data[blob]', [])
                            if blob_list:
                                self.data_blob = unquote(blob_list[0])
                                self.logger.info(f"✓ Captured data_blob from POST data: {self.data_blob}")
                                await self.solve_with_2captcha()
                        
                        try:
                            json_data = json.loads(post_data)
                            if 'blob' in json_data:
                                self.data_blob = json_data['blob']
                                self.logger.info(f"✓ Captured data_blob from JSON: {self.data_blob}")
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
                
                # Wait for frame to be ready
                try:
                    await frame.wait_for_load_state('domcontentloaded', timeout=10000)
                    self.logger.info("Frame DOM content loaded")
                    await frame.wait_for_load_state('networkidle', timeout=10000)
                    self.logger.info("Frame network idle")
                except Exception as e:
                    self.logger.error(f"Error waiting for frame load states: {e}")
                
                # First try URL parameters
                if 'data=' in url:
                    try:
                        data_param = re.search(r'data=([^&]+)', url)
                        if data_param:
                            self.data_blob = unquote(data_param.group(1))
                            self.logger.info(f"✓ Captured data_blob from frame URL: {self.data_blob}")
                            return
                    except Exception as e:
                        self.logger.debug(f"Failed to extract data from URL: {e}")
                
                # Then try JavaScript context with retry
                for attempt in range(3):
                    try:
                        data_blob = await frame.evaluate('''
                            () => {
                                // Try multiple methods to find data_blob
                                const blob = window.data_blob || 
                                           window.AKROSE_DATA_BLOB || 
                                           document.querySelector('[data-blob]')?.getAttribute('data-blob') ||
                                           document.querySelector('script[type="text/javascript"]')?.textContent.match(/data_blob["']?\s*[:=]\s*["']([^"']+)["']/)?.[1];
                                
                                // Also try URL parameters
                                if (!blob) {
                                    const urlParams = new URLSearchParams(window.location.search);
                                    return urlParams.get('data') || urlParams.get('blob');
                                }
                                return blob;
                            }
                        ''')
                        
                        if data_blob:
                            self.data_blob = data_blob
                            self.logger.info(f"✓ Captured data_blob from frame JS (attempt {attempt + 1}): {self.data_blob}")
                            return
                        
                        await asyncio.sleep(1)
                    except Exception as e:
                        self.logger.debug(f"Failed attempt {attempt + 1} to extract data from frame JS: {e}")
                        await asyncio.sleep(1)
                    
        except Exception as e:
            self.logger.error(f"Error in frame handler: {e}")
    
    async def extract_data_blob_via_evaluate(self):
        """Extract data_blob with enhanced methods."""
        try:
            # First try to get data_blob from the main page
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
                return
            
            # If not found, try to find it in iframes
            frames = self.page.frames
            for frame in frames:
                if 'arkoselabs' in frame.url:
                    self.logger.info(f"Checking frame: {frame.url}")
                    try:
                        frame_blob = await frame.evaluate('''
                            () => {
                                // Try multiple methods in frame
                                const blob = window.data_blob || 
                                           window.AKROSE_DATA_BLOB ||
                                           document.querySelector('[data-blob]')?.getAttribute('data-blob') ||
                                           document.querySelector('script[type="text/javascript"]')?.textContent.match(/data_blob["']?\s*[:=]\s*["']([^"']+)["']/)?.[1];
                                
                                // Also try to find it in URL parameters
                                if (!blob) {
                                    const urlParams = new URLSearchParams(window.location.search);
                                    return urlParams.get('data') || urlParams.get('blob');
                                }
                                return blob;
                            }
                        ''')
                        if frame_blob:
                            self.data_blob = frame_blob
                            self.logger.info(f"✓ Captured data_blob from frame: {self.data_blob}")
                            await self.take_frame_screenshot(frame.url)
                            return
                    except Exception as frame_error:
                        self.logger.error(f"Error extracting from frame: {frame_error}")
                        continue
            
            self.logger.error("Could not find data_blob in page or frames")
            
        except Exception as e:
            self.logger.error(f"Error extracting data_blob via evaluate: {e}")

    async def solve_captcha_challenge(self) -> bool:
        """Main captcha solving workflow with enhanced retry."""
        try:
            if not self.data_blob:
                self.logger.info("Attempting to extract data_blob...")
                start_time = time.time()
                
                # First wait for Arkose frame to appear
                arkose_frame = None
                while not arkose_frame and time.time() - start_time < 30:
                    for frame in self.page.frames:
                        if 'arkoselabs' in frame.url:
                            arkose_frame = frame
                            self.logger.info(f"Found Arkose frame: {frame.url}")
                            break
                    if not arkose_frame:
                        await asyncio.sleep(1)
                
                if not arkose_frame:
                    self.logger.error("Could not find Arkose frame after 30 seconds")
                    return False
                
                # Wait for frame to load completely
                try:
                    await arkose_frame.wait_for_load_state('networkidle', timeout=10000)
                    self.logger.info("Arkose frame finished loading")
                except Exception as e:
                    self.logger.error(f"Error waiting for frame load: {e}")
                
                # Now try to extract data_blob
                while not self.data_blob and time.time() - start_time < 60:
                    # Try main page first
                    await self.extract_data_blob_via_evaluate()
                    if self.data_blob:
                        break
                        
                    # Then try the Arkose frame
                    try:
                        await self.handle_frame(arkose_frame)
                        if self.data_blob:
                            break
                    except Exception as e:
                        self.logger.error(f"Error handling Arkose frame: {e}")
                    
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

            # Format proxy string with URL encoding
            try:
                username = quote(self.proxy_config['proxy_username'], safe='')
                password = quote(self.proxy_config['proxy_password'], safe='')
                proxy_str = f"{username}:{password}@{self.proxy_config['proxy_url']}:{self.proxy_config['proxy_port']}"
                self.logger.info(f"Successfully prepared proxy string with username and proxy URL")
            except Exception as e:
                self.logger.error(f"Failed to prepare proxy string: {str(e)}")
                self.logger.error(f"Proxy config keys available: {list(self.proxy_config.keys())}")
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
                'captchatype': 'FunCaptchaTask',
                'useragent': self.user_agent,
                'data': json.dumps({                           # Data as a JSON string
                    "blob": self.data_blob,
                    "blobFromArkoselabs": "1"
                }),
                'nojs': 0,
                'soft_id': 0
            }

            self.logger.info(f"Sending 2Captcha request (Attempt {attempt}/{max_attempts})")
            self.logger.debug(f"Payload: {json.dumps(payload, indent=2)}")

            transport = httpx.AsyncHTTPTransport(
                proxy=httpx.URL(f"http://{proxy_str}"),
                verify=False,
                retries=2
            )
            
            async with httpx.AsyncClient(
                transport=transport,
                timeout=httpx.Timeout(30.0),
                verify=False,
                follow_redirects=True,
                http2=False
            ) as client:
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
                        
                        token = await self._poll_2captcha_result(client, captcha_id, self.TWO_CAPTCHA_KEY)
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
