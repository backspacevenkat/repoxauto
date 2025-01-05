import asyncio
import logging
import ssl
import json
import time
from typing import List, Dict
from urllib.parse import quote
import httpx
from ..models.account import ValidationState

logger = logging.getLogger(__name__)

async def check_ip(proxy_config: dict) -> str:
    """Check IP using proxy configuration."""
    try:
        # URL encode credentials
        username = quote(proxy_config['proxyLogin'], safe='')
        password = quote(proxy_config['proxyPassword'], safe='')
        # Format proxy URL with proper encoding and protocol
        proxy_url = f"http://{username}:{password}@{proxy_config['proxyAddress']}:{proxy_config['proxyPort']}"
        logger.info(f"Proxy URL format: {proxy_url.replace(password, '****')}")  # Log URL with hidden password

        # Try multiple IP check services
        ip_services = [
            'https://api.ipify.org',
            'https://ifconfig.me/ip',
            'https://icanhazip.com'
        ]
        
        # Log proxy configuration
        logger.info(f"Using proxy configuration: {proxy_url}")
        
        # Create transport with SSL context
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Configure client with proper proxy settings
        transport = httpx.AsyncHTTPTransport(
            proxy=httpx.URL(f"http://{username}:{password}@{proxy_config['proxyAddress']}:{proxy_config['proxyPort']}"),
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

async def check_account_status(account: dict, proxy_config: dict) -> str:
    """Check Twitter account status using GraphQL API."""
    try:
        # Format proxy URL
        username = quote(proxy_config['proxyLogin'], safe='')
        password = quote(proxy_config['proxyPassword'], safe='')
        proxy_url = f"http://{username}:{password}@{proxy_config['proxyAddress']}:{proxy_config['proxyPort']}"

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

        # Log proxy configuration
        logger.info(f"Using proxy configuration: {proxy_url}")
        
        # Create transport with SSL context
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Configure client with proper proxy settings
        transport = httpx.AsyncHTTPTransport(
            proxy=httpx.URL(f"http://{username}:{password}@{proxy_config['proxyAddress']}:{proxy_config['proxyPort']}"),
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
                        return "suspended"
                    elif error_code == 50:
                        return "not_found"
                    elif error_code == 215:
                        return "invalid_auth"
                    elif error_code == 88:
                        return "rate_limited"
                    else:
                        return f"error_{error_code}"
                except:
                    return f"error_{response.status_code}"

            response_data = response.json()
            if 'data' in response_data and 'user' in response_data['data']:
                user_data = response_data['data']['user']['result']
                if user_data.get('__typename') == 'UserUnavailable':
                    return "unavailable"
                else:
                    legacy_data = user_data.get('legacy', {})
                    if legacy_data.get('verified_type') == 'Developer':
                        return "active (Developer)"
                    return "active"
            else:
                return "not_found"

    except httpx.ProxyError as e:
        logger.error(f"Proxy connection error: {str(e)}")
        return f"proxy_error: {str(e)}"
    except httpx.TimeoutException as e:
        logger.error(f"Request timed out: {str(e)}")
        return f"timeout: {str(e)}"
    except httpx.ConnectError as e:
        logger.error(f"Connection error: {str(e)}")
        return f"connection_error: {str(e)}"
    except httpx.ReadError as e:
        logger.error(f"Read error: {str(e)}")
        return f"read_error: {str(e)}"
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
            
        return status

async def validate_account(account_dict: dict) -> str:
    """Validate a single account"""
    try:
        logger.info(f"Starting validation for account {account_dict.get('account_no')}")

        # Get proxy config from account details
        proxy_config = {
            'proxyLogin': account_dict['proxy_username'],
            'proxyPassword': account_dict['proxy_password'],
            'proxyAddress': account_dict['proxy_url'],
            'proxyPort': account_dict['proxy_port']
        }

        # Check account status directly without IP check
        try:
            logger.info(f"Checking status for account {account_dict['account_no']}")
            status = await check_account_status(account_dict, proxy_config)
            logger.info(f"Status for account {account_dict['account_no']}: {status}")
            return status
        except Exception as e:
            logger.error(f"Error in check_account_status: {e}")
            return f"Error: {str(e)}"

    except Exception as e:
        logger.error(f"Error validating account {account_dict.get('account_no')}: {e}")
        return f"Error: {str(e)}"

async def validate_accounts_parallel(accounts: List[dict], max_workers: int = 6) -> List[Dict[str, str]]:
    """Validate multiple accounts in parallel"""
    results = []
    semaphore = asyncio.Semaphore(max_workers)

    async def validate_with_semaphore(account: dict):
        async with semaphore:
            try:
                status = await validate_account(account)
                return {
                    "account_no": account["account_no"],
                    "status": status
                }
            except Exception as e:
                logger.error(f"Error validating account {account.get('account_no')}: {e}")
                return {
                    "account_no": account["account_no"],
                    "status": f"Error: {str(e)}"
                }

    # Create tasks for all accounts
    tasks = []
    for account in accounts:
        # Add logging for account details
        logger.info(f"Creating validation task for account {account.get('account_no')}")
        tasks.append(validate_with_semaphore(account))
    
    # Execute tasks in parallel and gather results
    try:
        completed = await asyncio.gather(*tasks)
        results.extend([r for r in completed if r])
    except Exception as e:
        logger.error(f"Error in parallel validation: {e}")
    
    return results
