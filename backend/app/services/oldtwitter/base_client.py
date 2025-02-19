import logging
import httpx
import json
import uuid
import random
import asyncio
import time
from typing import Dict, Optional, Any
from urllib.parse import urlparse, quote
from datetime import datetime, timezone

from .oauth_utils import (
    construct_proxy_url,
    create_oauth_params,
    generate_oauth_signature,
    create_auth_header
)
from .types import ProxyConfig, API_ENDPOINTS, GRAPHQL_ENDPOINTS, DEFAULT_FEATURES

logger = logging.getLogger(__name__)

class BaseTwitterClient:
    def __init__(
        self,
        account_no: str,
        auth_token: str,
        ct0: str,
        consumer_key: Optional[str] = None,
        consumer_secret: Optional[str] = None,
        bearer_token: Optional[str] = None,
        access_token: Optional[str] = None,
        access_token_secret: Optional[str] = None,
        client_id: Optional[str] = None,
        proxy_config: Optional[ProxyConfig] = None,
        user_agent: Optional[str] = None
    ):
        """Initialize base Twitter client with authentication and configuration"""
        self.account_no = account_no
        self.auth_token = auth_token
        self.ct0 = ct0
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.bearer_token = bearer_token
        self.access_token = access_token
        self.access_token_secret = access_token_secret
        self.client_id = client_id
        self.proxy_config = proxy_config
        self.proxy_url = None
        self.client = None
        
        # Set default user agent if none provided
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/91.0.4472.124 Safari/537.36"
        )
        
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
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-client-language': 'en',
            'x-twitter-active-user': 'yes'
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
            'Referer': 'https://x.com/',
            'User-Agent': self.user_agent,
            'accept': '*/*',
            'Accept': '*/*'
        }

    async def graphql_request(
        self,
        endpoint_name: str,
        variables: Dict,
        features: Optional[Dict] = None
    ) -> Dict:
        """Make a GraphQL request with proper parameter encoding"""
        endpoint_id = GRAPHQL_ENDPOINTS.get(endpoint_name)
        if not endpoint_id:
            raise ValueError(f"Unknown GraphQL endpoint: {endpoint_name}")

        try:
            # First get a guest token
            guest_token_response = await self._make_request(
                method="POST",
                url="https://api.twitter.com/1.1/guest/activate.json",
                headers={
                    'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA'
                }
            )
            
            guest_token = guest_token_response.get('guest_token')
            if not guest_token:
                raise Exception("Failed to get guest token")

            # Update headers for GraphQL request
            headers = {
                'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
                'x-csrf-token': self.ct0,
                'cookie': f'auth_token={self.auth_token}; ct0={self.ct0}',
                'content-type': 'application/json',
                'x-twitter-auth-type': 'OAuth2Session',
                'x-twitter-client-language': 'en',
                'x-twitter-active-user': 'yes',
                'User-Agent': self.user_agent,
                'x-client-transaction-id': f'client-tx-{uuid.uuid4()}',
                'accept': '*/*',
                'accept-language': 'en-US,en;q=0.9',
                'origin': 'https://twitter.com',
                'referer': 'https://twitter.com/',
                'x-guest-token': guest_token,
                'x-twitter-client-uuid': str(uuid.uuid4())
            }

            # Build URL with proper endpoint structure
            url = f"https://api.twitter.com/graphql/{endpoint_id}/{endpoint_name}"
            
            # Make request with properly formatted parameters
            response = await self._make_request(
                method="POST",
                url=url,
                json_data={
                    "variables": variables,
                    "features": features or DEFAULT_FEATURES,
                    "queryId": endpoint_id
                },
                headers=headers
            )

            if 'errors' in response:
                error_msg = response['errors'][0].get('message', 'Unknown error')
                raise Exception(f"GraphQL error: {error_msg}")

            return response

        except Exception as e:
            logger.error(f"GraphQL request failed: {str(e)}")
            raise

    async def _init_client(self):
        """Initialize HTTP client with proxy if configured"""
        try:
            # If client exists and is still active, return
            if self.client and not self.client.is_closed:
                return

            # Close existing client if it exists
            if self.client:
                try:
                    await self.client.aclose()
                except:
                    pass
                self.client = None

            # Basic client configuration
            client_config = {
                "timeout": httpx.Timeout(
                    connect=random.uniform(20.0, 30.0),
                    read=random.uniform(45.0, 60.0),
                    write=random.uniform(45.0, 60.0),
                    pool=random.uniform(45.0, 60.0)
                ),
                "follow_redirects": True,
                "verify": False,  # Disable SSL verification for proxies
                "http2": False,  # Disable HTTP/2 to avoid SSL issues
                "trust_env": False,  # Don't use system proxy settings
                "limits": httpx.Limits(
                    max_keepalive_connections=random.randint(3, 7),
                    max_connections=random.randint(8, 12),
                    keepalive_expiry=random.uniform(25.0, 35.0)
                ),
                "transport": httpx.AsyncHTTPTransport(retries=5)
            }

            # Add proxy configuration if available
            if self.proxy_config:
                try:
                    self.proxy_url = construct_proxy_url(
                        username=self.proxy_config['proxy_username'],
                        password=self.proxy_config['proxy_password'],
                        host=self.proxy_config['proxy_url'],
                        port=self.proxy_config['proxy_port']
                    )
                    
                    # Test proxy URL format
                    parsed = urlparse(self.proxy_url)
                    if not all([parsed.scheme, parsed.hostname, parsed.port]):
                        raise ValueError("Invalid proxy URL format")
                    
                    transport = httpx.AsyncHTTPTransport(
                        proxy=httpx.URL(self.proxy_url),
                        verify=False,
                        retries=2,
                        trust_env=False
                    )
                    client_config["transport"] = transport
                    
                    logger.info(f"Successfully configured proxy for account {self.account_no}")
                    
                except Exception as e:
                    logger.error(f"Failed to configure proxy for account {self.account_no}: {str(e)}")
                    self.proxy_url = None
                    raise ValueError(f"Failed to configure proxy: {str(e)}")

            # Initialize client
            self.client = httpx.AsyncClient(**client_config)
            logger.info(f"Successfully initialized client for account {self.account_no}")
            
        except Exception as e:
            logger.error(f"Failed to initialize client: {str(e)}")
            if self.client:
                try:
                    await self.client.aclose()
                except:
                    pass
                self.client = None
            raise Exception(f"Failed to initialize HTTP client: {str(e)}")

    async def _make_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        files: Optional[Dict] = None,
        data: Optional[Dict] = None
    ) -> Dict:
        """Make HTTP request with proper OAuth handling and error handling"""
        try:
            # Initialize client if needed
            if not self.client or self.client.is_closed:
                await self._init_client()
            
            if not self.client:
                raise Exception("Failed to initialize HTTP client")

            # Handle parameters without double encoding
            if params:
                params = {k: v for k, v in params.items()}

            # Select appropriate headers based on URL and request type
            request_headers = {}
            
            if 'upload.twitter.com' in url:
                # For media uploads, only oauth_* parameters in signature
                oauth_params = create_oauth_params(self.consumer_key, self.access_token)
                signature = generate_oauth_signature(
                    method,
                    url,
                    oauth_params,
                    self.consumer_secret,
                    self.access_token_secret
                )
                oauth_params['oauth_signature'] = signature
                request_headers = {
                    'Authorization': create_auth_header(oauth_params),
                    'Accept': 'application/json'
                }
                
            elif 'api.twitter.com/2/' in url:
                # API v2 endpoints with OAuth 1.0a
                oauth_params = create_oauth_params(self.consumer_key, self.access_token)
                signature = generate_oauth_signature(
                    method,
                    url,
                    oauth_params,
                    self.consumer_secret,
                    self.access_token_secret
                )
                oauth_params['oauth_signature'] = signature
                request_headers = {
                    'Authorization': create_auth_header(oauth_params),
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                }
                
            elif 'api.twitter.com/1.1/' in url:
                # API v1.1 endpoints with OAuth 1.0a including params
                oauth_params = create_oauth_params(self.consumer_key, self.access_token)
                
                # Combine OAuth params with request params for signature
                all_params = {**oauth_params}
                if params:
                    all_params.update(params)
                if json_data:
                    # Flatten nested JSON for OAuth signature
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
                request_headers = {
                    'Authorization': create_auth_header(oauth_params),
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                }
                
            elif 'x.com/i/api/graphql' in url or 'twitter.com/i/api/graphql' in url:
                request_headers = self.graphql_headers.copy()
                # Update origin and referer for x.com
                request_headers.update({
                    'origin': 'https://x.com',
                    'referer': 'https://x.com/'
                })

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

            # Add any custom headers
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

            # Handle files and data appropriately
            if files:
                if data:
                    # Combine files and form data
                    multipart_data = {}
                    for key, value in data.items():
                        multipart_data[key] = (None, str(value))
                    multipart_data.update(files)
                    request_kwargs['files'] = multipart_data
                else:
                    request_kwargs['files'] = files
                # Remove content-type for multipart
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
                        logger.warning(f'Rate limited. Waiting {retry_after} seconds...')
                        await asyncio.sleep(retry_after)
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
            logger.error(f'Error in _make_request: {str(e)}')
            raise

    async def close(self):
        """Close HTTP client and cleanup transport"""
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
