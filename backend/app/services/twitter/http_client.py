import httpx
import logging
import asyncio
import random
import uuid
import json
import ssl
import time
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse, quote, urlencode
from datetime import datetime, timezone

from .auth import generate_oauth_signature, generate_nonce, construct_proxy_url
from .utils.constants import DEFAULT_HEADERS, DEFAULT_FEATURES, GRAPHQL_ENDPOINTS

logger = logging.getLogger(__name__)

class TwitterHttpClient:
    def __init__(
        self,
        auth_token: str,
        ct0: str,
        consumer_key: str,
        consumer_secret: str,
        bearer_token: str,
        access_token: str,
        access_token_secret: str,
        proxy_config: Optional[Dict[str, str]] = None,
        user_agent: Optional[str] = None
    ):
        """Initialize TwitterHttpClient with authentication and configuration"""
        self.auth_token = auth_token
        self.ct0 = ct0
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.bearer_token = bearer_token
        self.access_token = access_token
        self.access_token_secret = access_token_secret
        self.proxy_config = proxy_config
        self.client = None
        self.proxy_url = None
        
        # Set default user agent if none provided
        self.user_agent = user_agent or DEFAULT_HEADERS['User-Agent']
        
        # Initialize headers
        self.headers = {
            'authorization': f'Bearer {self.bearer_token}',
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-client-language': 'en',
            'x-twitter-active-user': 'yes',
            'content-type': 'application/json',
            'x-csrf-token': self.ct0,
            'cookie': f'auth_token={self.auth_token}; ct0={self.ct0}'
        }
        
        # API v2 specific headers
        self.api_v2_headers = {
            'authorization': f'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
            'content-type': 'application/json',
            'cookie': f'auth_token={self.auth_token}; ct0={self.ct0}',
            'x-csrf-token': self.ct0,
            'x-twitter-auth-type': 'OAuth2Session'
        }
        
        # GraphQL specific headers
        self.graphql_headers = {
            'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
            'x-csrf-token': self.ct0,
            'cookie': f'auth_token={self.auth_token}; ct0={self.ct0}',
            'content-type': 'application/json',
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-client-language': 'en',
            'x-twitter-active-user': 'yes',
            'Referer': 'https://twitter.com/',
            'User-Agent': self.user_agent,
            'accept': '*/*',
            'Accept': '*/*'
        }

        # Configure proxy if provided
        if proxy_config:
            self._configure_proxy(proxy_config)

    def _configure_proxy(self, proxy_config: Dict[str, str]):
        """Configure proxy settings from provided configuration"""
        try:
            username = proxy_config.get('proxy_username')
            password = proxy_config.get('proxy_password')
            host = proxy_config.get('proxy_url')
            port = proxy_config.get('proxy_port')

            if not all([username, password, host, port]):
                missing = []
                if not username: missing.append('proxy_username')
                if not password: missing.append('proxy_password')
                if not host: missing.append('proxy_url')
                if not port: missing.append('proxy_port')
                raise ValueError(f"Missing proxy configuration: {', '.join(missing)}")

            self.proxy_url = construct_proxy_url(username, password, host, port)

            # Validate proxy URL
            parsed = urlparse(self.proxy_url)
            if not parsed.scheme or not parsed.hostname or not parsed.port:
                raise ValueError("Invalid proxy URL format after construction")

            logger.info(f"Successfully configured proxy")

        except Exception as e:
            logger.error(f"Failed to configure proxy: {str(e)}")
            self.proxy_url = None
            raise

    async def _init_client(self):
        """Initialize HTTP client with retry logic and proxy support"""
        try:
            if self.client and not self.client.is_closed:
                return

            if self.client:
                try:
                    await self.client.aclose()
                except:
                    pass
                self.client = None

            client_config = {
                "timeout": httpx.Timeout(
                    connect=random.uniform(20.0, 30.0),
                    read=random.uniform(45.0, 60.0),
                    write=random.uniform(45.0, 60.0),
                    pool=random.uniform(45.0, 60.0)
                ),
                "follow_redirects": True,
                "verify": False,
                "http2": False,
                "trust_env": False,
                "limits": httpx.Limits(
                    max_keepalive_connections=random.randint(3, 7),
                    max_connections=random.randint(8, 12),
                    keepalive_expiry=random.uniform(25.0, 35.0)
                ),
                "transport": httpx.AsyncHTTPTransport(retries=5)
            }

            if self.proxy_url:
                try:
                    proxy_url = httpx.URL(self.proxy_url)
                    transport = httpx.AsyncHTTPTransport(
                        proxy=proxy_url,
                        verify=False,
                        retries=2,
                        trust_env=False
                    )
                    client_config["transport"] = transport
                except Exception as e:
                    logger.error(f"Failed to configure proxy transport: {str(e)}")
                    raise

            self.client = httpx.AsyncClient(**client_config)
            logger.info("Successfully initialized HTTP client")

        except Exception as e:
            logger.error(f"Failed to initialize client: {str(e)}")
            if self.client:
                await self.client.aclose()
                self.client = None
            raise

    def _get_upload_headers(self, method: str, url: str) -> Dict:
        """Get headers for media upload endpoints"""
        oauth_params = {
            'oauth_consumer_key': self.consumer_key,
            'oauth_nonce': generate_nonce(),
            'oauth_signature_method': 'HMAC-SHA1',
            'oauth_timestamp': str(int(time.time())),
            'oauth_token': self.access_token,
            'oauth_version': '1.0'
        }
        
        signature = generate_oauth_signature(
            method,
            url,
            oauth_params,
            self.consumer_secret,
            self.access_token_secret
        )
        oauth_params['oauth_signature'] = signature
        
        auth_header = 'OAuth ' + ', '.join(
            f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
            for k, v in sorted(oauth_params.items())
        )
        
        return {
            'Authorization': auth_header,
            'Accept': 'application/json'
        }

    def _get_api_v2_headers(self, method: str, url: str, params: Optional[Dict] = None) -> Dict:
        """Get headers for API v2 endpoints"""
        oauth_params = {
            'oauth_consumer_key': self.consumer_key,
            'oauth_nonce': generate_nonce(),
            'oauth_signature_method': 'HMAC-SHA1',
            'oauth_timestamp': str(int(time.time())),
            'oauth_token': self.access_token,
            'oauth_version': '1.0'
        }
        
        signature = generate_oauth_signature(
            method,
            url,
            oauth_params,
            self.consumer_secret,
            self.access_token_secret
        )
        oauth_params['oauth_signature'] = signature
        
        auth_header = 'OAuth ' + ', '.join(
            f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
            for k, v in sorted(oauth_params.items())
        )
        
        return {
            'Authorization': auth_header,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def _get_api_v1_headers(self, method: str, url: str, params: Optional[Dict] = None, json_data: Optional[Dict] = None) -> Dict:
        """Get headers for API v1.1 endpoints"""
        oauth_params = {
            'oauth_consumer_key': self.consumer_key,
            'oauth_nonce': generate_nonce(),
            'oauth_signature_method': 'HMAC-SHA1',
            'oauth_timestamp': str(int(time.time())),
            'oauth_token': self.access_token,
            'oauth_version': '1.0'
        }
        
        all_params = {**oauth_params}
        if params:
            all_params.update(params)
        if json_data:
            flat_data = {}
            for k, v in json_data.items():
                if isinstance(v, dict):
                    for sub_k, sub_v in v.items():
                        flat_data[f"{k}.{sub_k}"] = str(sub_v)
                else:
                    flat_data[k] = str(v)
            all_params.update(flat_data)
            
        signature = generate_oauth_signature(
            method,
            url,
            all_params,
            self.consumer_secret,
            self.access_token_secret
        )
        oauth_params['oauth_signature'] = signature
        
        auth_header = 'OAuth ' + ', '.join(
            f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
            for k, v in sorted(oauth_params.items())
        )
        
        return {
            'Authorization': auth_header,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    async def _handle_rate_limit(self, retry_after: int):
        """Handle rate limiting with exponential backoff"""
        logger.warning(f'Rate limited. Waiting {retry_after} seconds...')
        await asyncio.sleep(retry_after)

    async def make_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        files: Optional[Dict] = None,
        data: Optional[Dict] = None
    ) -> Dict:
        """Make HTTP request with proper OAuth handling and retry logic"""
        try:
            if not self.client or self.client.is_closed:
                await self._init_client()

            if not self.client:
                raise Exception("Failed to initialize HTTP client")

            # Handle parameters
            if params:
                params = {k: v for k, v in params.items()}

            # Add small random delay between requests
            await asyncio.sleep(random.uniform(0.5, 2.0))

            # Select appropriate headers
            request_headers = {}
            
            if 'upload.twitter.com' in url:
                request_headers = self._get_upload_headers(method, url)
            elif 'api.twitter.com/2/' in url:
                request_headers = self._get_api_v2_headers(method, url, params)
            elif 'api.twitter.com/1.1/' in url:
                request_headers = self._get_api_v1_headers(method, url, params, json_data)
            elif 'twitter.com/i/api/graphql' in url:
                request_headers = self.graphql_headers.copy()

            # Add dynamic headers
            request_headers.update({
                'User-Agent': self.user_agent,
                'x-client-uuid': str(uuid.uuid4()),
                'accept-language': random.choice([
                    'en-US,en;q=0.9',
                    'en-GB,en;q=0.9',
                    'en-CA,en;q=0.9'
                ])
            })

            # Add custom headers
            if headers:
                request_headers.update(headers)

            # Prepare request kwargs
            request_kwargs = {
                'method': method,
                'url': url,
                'params': params,
                'headers': request_headers,
                'follow_redirects': True
            }

            # Handle files and data
            if files:
                if data:
                    multipart_data = {}
                    for key, value in data.items():
                        multipart_data[key] = (None, str(value))
                    multipart_data.update(files)
                    request_kwargs['files'] = multipart_data
                else:
                    request_kwargs['files'] = files
                if 'Content-Type' in request_kwargs['headers']:
                    del request_kwargs['headers']['Content-Type']
            elif data:
                request_kwargs['data'] = data
            elif json_data:
                request_kwargs['json'] = json_data

            # Make request with retries
            MAX_RETRIES = 3
            retry_count = 0
            
            while retry_count < MAX_RETRIES:
                try:
                    response = await self.client.request(**request_kwargs)
                    
                    # Handle rate limiting
                    if response.status_code == 429:
                        retry_after = int(response.headers.get('retry-after', '60'))
                        await self._handle_rate_limit(retry_after)
                        retry_count += 1
                        continue

                    # Handle auth errors
                    if response.status_code in (401, 403):
                        logger.error(f'Authentication failed: {response.text}')
                        raise Exception('Authentication failed - check credentials')

                    # Handle successful responses
                    if response.status_code == 204:  # No Content
                        return {}
                        
                    response.raise_for_status()
                    
                    try:
                        return response.json()
                    except json.JSONDecodeError:
                        if response.content:
                            logger.warning(f'Could not decode JSON response: {response.content[:200]}')
                        return {}

                except httpx.TimeoutException:
                    logger.warning(f'Request timeout (attempt {retry_count + 1}/{MAX_RETRIES})')
                    retry_count += 1
                    if retry_count < MAX_RETRIES:
                        await asyncio.sleep(2 ** retry_count)  # Exponential backoff
                    continue
                except Exception as e:
                    logger.error(f'Request error: {str(e)}')
                    raise

            raise Exception(f'Request failed after {MAX_RETRIES} retries')

        except Exception as e:
            logger.error(f'Error in make_request: {str(e)}')
            raise

    async def graphql_request(
        self,
        endpoint_name: str,
        variables: Dict,
        features: Optional[Dict] = None
    ) -> Dict:
        """Make a GraphQL request with updated headers and error handling"""
        endpoint_id = GRAPHQL_ENDPOINTS.get(endpoint_name)
        if not endpoint_id:
            raise ValueError(f"Unknown GraphQL endpoint: {endpoint_name}")

        # Add small random delay to simulate human behavior
        await asyncio.sleep(random.uniform(0.5, 2.0))
        
        try:
            base_url = "https://twitter.com/i/api/graphql"
            
            # Update headers with new transaction ID and client UUID
            headers = self.graphql_headers.copy()
            headers.update({
                'x-client-transaction-id': f'client-tx-{uuid.uuid4()}',
                'x-client-uuid': str(uuid.uuid4())
            })

            if endpoint_name in ['FavoriteTweet', 'CreateRetweet', 'CreateTweet']:
                # For mutations
                json_data = {
                    "variables": variables,
                    "features": features or DEFAULT_FEATURES,
                    "queryId": endpoint_id
                }
                
                response = await self.make_request(
                    "POST",
                    f"{base_url}/{endpoint_id}/{endpoint_name}",
                    json_data=json_data,
                    headers=headers
                )
            else:
                # For queries
                variables_json = json.dumps(variables, ensure_ascii=False)
                features_json = json.dumps(features or DEFAULT_FEATURES, ensure_ascii=False)
                
                response = await self.make_request(
                    "GET",
                    f"{base_url}/{endpoint_id}/{endpoint_name}",
                    params={
                        "variables": variables_json,
                        "features": features_json
                    },
                    headers=headers
                )
            
            if 'errors' in response:
                error_msg = response['errors'][0].get('message', 'Unknown error')
                logger.error(f"GraphQL error: {error_msg}")
                raise Exception(f"GraphQL error: {error_msg}")
                
            return response

        except Exception as e:
            logger.error(f"GraphQL request failed: {str(e)}")
            raise

    async def _send_client_event(self, event_namespace: dict, items: list = None):
        """Send client event using proper endpoint and format"""
        if items is None:
            items = []
            
        event_data = {
            "_category_": "client_event",
            "format_version": 2,
            "triggered_on": int(time.time() * 1000),
            "items": items,
            "event_namespace": event_namespace,
            "client_event_sequence_start_timestamp": int(time.time() * 1000) - 1000,
            "client_event_sequence_number": random.randint(100, 300),
            "client_app_id": "3033300"
        }
        
        log_data = json.dumps([event_data])
        
        form_data = {
            'debug': 'true',
            'log': log_data
        }

        headers = {
            **self.graphql_headers,
            'content-type': 'application/x-www-form-urlencoded',
            'x-client-transaction-id': f'client-tx-{uuid.uuid4()}',
            'x-client-uuid': str(uuid.uuid4()),
            'origin': 'https://twitter.com',
            'referer': 'https://twitter.com/home'
        }

        await self.make_request(
            "POST",
            "https://twitter.com/i/api/1.1/jot/client_event.json",
            data=form_data,
            headers=headers
        )

    async def upload_chunked_media(
        self,
        file_path: str,
        file_type: str,
        file_size: int,
        media_category: str,
        chunk_size: int = 4*1024*1024  # 4MB chunks
    ) -> str:
        """Upload large media files in chunks"""
        try:
            # INIT phase
            init_data = {
                'command': 'INIT',
                'total_bytes': str(file_size),
                'media_type': file_type,
                'media_category': media_category
            }

            init_response = await self.make_request(
                method="POST",
                url="https://upload.twitter.com/1.1/media/upload.json",
                data=init_data,
                headers=self._get_upload_headers("POST", "https://upload.twitter.com/1.1/media/upload.json")
            )

            if not init_response or 'media_id_string' not in init_response:
                raise Exception("Failed to initialize media upload")

            media_id = init_response['media_id_string']

            # APPEND phase
            with open(file_path, 'rb') as file:
                segment_index = 0
                while True:
                    chunk = file.read(chunk_size)
                    if not chunk:
                        break

                    append_data = {
                        'command': 'APPEND',
                        'media_id': media_id,
                        'segment_index': str(segment_index)
                    }

                    files = {
                        'media': chunk
                    }

                    await self.make_request(
                        method="POST",
                        url="https://upload.twitter.com/1.1/media/upload.json",
                        data=append_data,
                        files=files,
                        headers=self._get_upload_headers("POST", "https://upload.twitter.com/1.1/media/upload.json")
                    )

                    segment_index += 1

            # FINALIZE phase
            finalize_data = {
                'command': 'FINALIZE',
                'media_id': media_id
            }

            finalize_response = await self.make_request(
                method="POST",
                url="https://upload.twitter.com/1.1/media/upload.json",
                data=finalize_data,
                headers=self._get_upload_headers("POST", "https://upload.twitter.com/1.1/media/upload.json")
            )

            # Check if we need to wait for processing
            if finalize_response.get('processing_info'):
                await self._wait_for_media_processing(media_id)

            return media_id

        except Exception as e:
            logger.error(f"Error uploading chunked media: {str(e)}")
            raise

    async def _wait_for_media_processing(self, media_id: str, max_attempts: int = 10):
        """Wait for media processing to complete"""
        attempt = 0
        while attempt < max_attempts:
            status_response = await self.make_request(
                method="GET",
                url="https://upload.twitter.com/1.1/media/upload.json",
                params={'command': 'STATUS', 'media_id': media_id},
                headers=self._get_upload_headers("GET", "https://upload.twitter.com/1.1/media/upload.json")
            )

            processing_info = status_response.get('processing_info', {})
            state = processing_info.get('state')

            if state == 'succeeded':
                return
            elif state == 'failed':
                raise Exception(f"Media processing failed: {processing_info.get('error', {}).get('message')}")
            
            check_after_secs = processing_info.get('check_after_secs', 5)
            await asyncio.sleep(check_after_secs)
            attempt += 1

        raise Exception("Media processing timed out")

    async def close(self):
        """Close HTTP client and cleanup resources"""
        if self.client:
            try:
                await self.client.aclose()
            except Exception as e:
                logger.error(f"Error closing client: {str(e)}")
            finally:
                if hasattr(self.client, 'transport'):
                    try:
                        await self.client.transport.aclose()
                    except Exception as e:
                        logger.error(f"Error closing transport: {str(e)}")
                self.client = None