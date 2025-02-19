import asyncio
import logging
import ssl
import json
import time
from typing import List, Dict
from urllib.parse import quote
from datetime import datetime
import httpx
from sqlalchemy import select, literal_column, update
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.account import ValidationState, Account
from ..database import get_db

logger = logging.getLogger(__name__)

# Rest of the file content remains the same...
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

async def check_account_status(account: dict, proxy_config: dict, db: AsyncSession = None) -> str:
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

            # Log raw response for debugging
            response_text = response.text
            logger.info(f"Raw response: {response_text}")
            
            try:
                response_data = response.json()
                logger.info(f"Response data structure: {json.dumps(response_data, indent=2)}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response: {str(e)}")
                return "error"
            
            # First check for error extensions code 326 which definitively indicates a locked account
            if 'errors' in response_data:
                for error in response_data['errors']:
                    extensions = error.get('extensions', {})
                    if extensions.get('code') == 326:
                        logger.info(f"Found locked account indicator: extensions code 326")
                        return "locked"
                    
                    # Also check bounce location in extensions
                    bounce = extensions.get('bounce', {})
                    if bounce and bounce.get('bounce_location') == 'https://twitter.com/account/access':
                        logger.info(f"Found locked account indicator: bounce to account/access")
                        return "locked"
                    
                    # Check error message for lock indicators
                    message = error.get('message', '').lower()
                    if any(phrase in message for phrase in [
                        'account is temporarily locked',
                        'to protect our users from spam',
                        'please log in to https://twitter.com to unlock your account'
                    ]):
                        logger.info(f"Found locked account indicator in message: {message}")
                        return "locked"
                    
                    # Check other error conditions
                    if 'suspended' in message:
                        return "suspended"
                    elif 'not found' in message:
                        return "not_found"
                    elif 'unauthorized' in message:
                        return "invalid_auth"
            
            # Check if we have an empty user object with errors (indicates locked account)
            if 'data' in response_data and 'user' in response_data['data']:
                user = response_data['data']['user']
                
                # If user is empty and we have errors, it's likely a locked account
                if not user and 'errors' in response_data:
                    for error in response_data['errors']:
                        extensions = error.get('extensions', {})
                        if extensions.get('code') == 326:
                            logger.info(f"Found locked account indicator: empty user with error code 326")
                            return "locked"
                
                # Handle case where user is None
                if user is None:
                    return "not_found"
                
                # Log the user data structure for debugging
                logger.info(f"User data structure: {json.dumps(user, indent=2)}")
                
                # Check for locked status in user object
                if isinstance(user, dict):
                    if user.get('reason', '').lower() == 'accountlocked':
                        return "locked"
                    if user.get('locked', False):
                        return "locked"
                    
                    # Handle case where result is missing but we have error indicators
                    if 'result' not in user and 'errors' in response_data:
                        for error in response_data['errors']:
                            if error.get('extensions', {}).get('code') == 326:
                                logger.info(f"Found locked account indicator: missing result with error code 326")
                                return "locked"
                    
                    # Handle case where result is missing
                    if 'result' not in user:
                        logger.error("User data missing 'result' field")
                        logger.info(f"Full user data: {json.dumps(user, indent=2)}")
                        return "error"
                    
                user_data = user['result']
                
                # Check for various lock indicators in the response
                if user_data.get('__typename') == 'UserUnavailable':
                    reason = user_data.get('reason', '').lower()
                    if 'locked' in reason:
                        return "locked"
                    return "unavailable"
                    
                if isinstance(user_data, dict):
                    if user_data.get('reason') == 'AccountLocked':
                        return "locked"
                    elif user_data.get('locked', False):
                        return "locked"
                    elif user_data.get('protected', False) and user_data.get('limited_actions', False):
                        return "locked"
                    
                    # Check legacy data
                    legacy_data = user_data.get('legacy', {})
                    if legacy_data.get('locked', False):
                        return "locked"
                    elif legacy_data.get('verified_type') == 'Developer':
                        return "active (Developer)"
                    return "active"
                else:
                    logger.error(f"Unexpected user_data type: {type(user_data)}")
                    return "error"
            else:
                logger.error("Response missing data.user structure")
                return "error"

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

from .account_recovery import recover_account

async def validate_account(account_dict: dict, broadcast_update=None, db=None) -> str:
    """Validate a single account with real-time status updates"""
    try:
        account_no = account_dict.get('account_no')
        logger.info(f"Starting validation for account {account_no}")

        # Get a new database session if not provided
        if db is None:
            db = await anext(get_db())

        # Ensure we have a valid session
        try:
            await db.execute(select(literal_column('1')))
        except Exception as e:
            logger.error(f"Invalid database session, getting new one: {e}")
            db = await anext(get_db())

        if broadcast_update:
            await broadcast_update({
                "account_no": account_no,
                "status": "validating",
                "message": "Starting validation..."
            })

        # Get proxy config from account details
        proxy_config = {
            'proxyLogin': account_dict['proxy_username'],
            'proxyPassword': account_dict['proxy_password'],
            'proxyAddress': account_dict['proxy_url'],
            'proxyPort': account_dict['proxy_port']
        }

        # Ensure password is included in account_dict for cookie refresh
        if 'password' not in account_dict:
            logger.error(f"Password missing for account {account_no}")
            return "Error: Password required for validation"

        # First attempt: Check account status with current cookies
        try:
            if broadcast_update:
                await broadcast_update({
                    "account_no": account_no,
                    "status": "checking",
                    "message": "Checking account status..."
                })

            logger.info(f"Checking status for account {account_no}")
            status = await check_account_status(account_dict, proxy_config, db)
            logger.info(f"Initial status for account {account_no}: {status}")

            # If status indicates authentication/access issues, try refreshing cookies
            if status in ["locked", "suspended", "invalid_auth", "error_32", "unauthorized", "unavailable"]:
                if broadcast_update:
                    await broadcast_update({
                        "account_no": account_no,
                        "status": "refreshing",
                        "message": f"Account {status}, attempting cookie refresh..."
                    })

                logger.info(f"Account {account_no} needs cookie refresh, status: {status}")
                
                # Import here to avoid circular imports
                from ..routers.accounts import refresh_cookies_internal
                refresh_result = await refresh_cookies_internal(account_dict)
                
                if refresh_result.get("success"):
                    logger.info(f"Successfully refreshed cookies for account {account_no}")
                    # Update account dict with new cookies
                    account_dict["ct0"] = refresh_result["ct0"]
                    account_dict["auth_token"] = refresh_result["auth_token"]
                    
                    # Update database with new credentials
                    await db.execute(
                        update(Account)
                        .where(Account.account_no == account_no)
                        .values(
                            ct0=refresh_result["ct0"],
                            auth_token=refresh_result["auth_token"]
                        )
                    )
                    await db.commit()
                    logger.info(f"Updated database with new credentials for account {account_no}")
                    
                    # Recheck status with new cookies
                    if broadcast_update:
                        await broadcast_update({
                            "account_no": account_no,
                            "status": "rechecking",
                            "message": "Checking status with new cookies..."
                        })
                    
                    # Get fresh session if needed
                    try:
                        await db.execute(select(literal_column('1')))
                    except Exception:
                        logger.info("Getting fresh database session after cookie refresh")
                        db = await anext(get_db())
                    
                    status = await check_account_status(account_dict, proxy_config, db)
                    logger.info(f"New status after cookie refresh: {status}")
                else:
                    logger.error(f"Cookie refresh failed for account {account_no}")
                    
                    # Only attempt recovery if cookie refresh failed
                    if status in ["locked", "suspended", "unavailable"]:
                        if broadcast_update:
                            await broadcast_update({
                                "account_no": account_no,
                                "status": "recovering",
                                "message": "Cookie refresh failed, attempting account recovery..."
                            })
                        
                        logger.info(f"Attempting recovery for account {account_no}")
                        recovery_result = await recover_account(account_dict, proxy_config)
                        
                        if recovery_result.startswith("RECOVERED"):
                            logger.info(f"Successfully recovered account {account_no}")
                            
                            # Parse recovery result for new credentials
                            try:
                                # Recovery result format: "RECOVERED:ct0:auth_token"
                                _, new_ct0, new_auth_token = recovery_result.split(":")
                                
                                # Update account dict
                                account_dict["ct0"] = new_ct0
                                account_dict["auth_token"] = new_auth_token
                                
                                # Update database with new credentials
                                await db.execute(
                                    update(Account)
                                    .where(Account.account_no == account_no)
                                    .values(
                                        ct0=new_ct0,
                                        auth_token=new_auth_token
                                    )
                                )
                                await db.commit()
                                logger.info(f"Updated database with new credentials after recovery for account {account_no}")
                            except Exception as e:
                                logger.error(f"Error updating credentials after recovery: {e}")
                            
                            if broadcast_update:
                                await broadcast_update({
                                    "account_no": account_no,
                                    "status": "recovered",
                                    "message": "Account recovered, checking final status..."
                                })
                            # Recheck status after recovery
                            # Get fresh session if needed
                            try:
                                await db.execute(select(literal_column('1')))
                            except Exception:
                                logger.info("Getting fresh database session after recovery")
                                db = await anext(get_db())
                            
                            status = await check_account_status(account_dict, proxy_config, db)
                            logger.info(f"Final status after recovery: {status}")
                        else:
                            logger.error(f"Failed to recover account {account_no}: {recovery_result}")
            
            # Send final status update
            if broadcast_update:
                await broadcast_update({
                    "account_no": account_no,
                    "status": "completed",
                    "message": f"Validation completed: {status}",
                    "validation_result": status
                })
            
            return status
            
        except Exception as e:
            logger.error(f"Error in check_account_status: {e}")
            return f"Error: {str(e)}"

    except Exception as e:
        logger.error(f"Error validating account {account_dict.get('account_no')}: {e}")
        return f"Error: {str(e)}"

async def validate_accounts_parallel(accounts: List[dict], max_workers: int = 6, broadcast_update=None, db=None) -> List[Dict[str, str]]:
    """Validate multiple accounts in parallel with real-time updates"""
    results = []
    semaphore = asyncio.Semaphore(max_workers)
    
    # Get database session if not provided
    if db is None:
        db = await anext(get_db())
    
    # Track recent timeouts
    recent_timeouts = []
    MAX_CONSECUTIVE_TIMEOUTS = 5  # Stop after 5 different accounts timeout
    TIMEOUT_PAUSE_DURATION = 300  # 5 minutes in seconds

    async def validate_with_semaphore(account: dict):
        nonlocal recent_timeouts
        
        async with semaphore:
            try:
                # Check if account was validated within last 24 hours and is active
                if (account.get('last_validation_time') and 
                    (datetime.utcnow() - account['last_validation_time']).total_seconds() < 86400 and
                    account.get('validation_in_progress') == ValidationState.COMPLETED and
                    account.get('is_active') and
                    account.get('last_validation') == 'active'):
                    result = {
                        "account_no": account["account_no"],
                        "status": "active (skipped - validated within 24h)"
                    }
                    results.append(result)
                    return result

                # Check if we need to pause due to consecutive timeouts
                if len(recent_timeouts) >= MAX_CONSECUTIVE_TIMEOUTS:
                    if broadcast_update:
                        await broadcast_update({
                            "status": "batch_paused",
                            "message": f"Detected {MAX_CONSECUTIVE_TIMEOUTS} consecutive timeouts on different accounts. Pausing for 5 minutes...",
                            "timeout_accounts": recent_timeouts
                        })
                    
                    # Wait 5 minutes
                    await asyncio.sleep(TIMEOUT_PAUSE_DURATION)
                    
                    # Reset timeout tracking
                    recent_timeouts = []
                    
                    if broadcast_update:
                        await broadcast_update({
                            "status": "batch_resumed",
                            "message": "Resuming validation after pause..."
                        })

                status = await validate_account(account, broadcast_update, db)
                
                # Track timeouts
                if "timeout" in status.lower():
                    if account["account_no"] not in recent_timeouts:
                        recent_timeouts.append(account["account_no"])
                        if broadcast_update:
                            await broadcast_update({
                                "status": "timeout_tracking",
                                "message": f"Timeout detected ({len(recent_timeouts)}/{MAX_CONSECUTIVE_TIMEOUTS})",
                                "timeout_accounts": recent_timeouts
                            })
                else:
                    # Reset timeout tracking on successful validation
                    recent_timeouts = []
                
                result = {
                    "account_no": account["account_no"],
                    "status": status
                }
                results.append(result)  # Add result immediately
                return result
            except Exception as e:
                error_msg = f"Error: {str(e)}"
                logger.error(f"Error validating account {account.get('account_no')}: {e}")
                result = {
                    "account_no": account["account_no"],
                    "status": error_msg
                }
                results.append(result)  # Add error result immediately
                
                if broadcast_update:
                    await broadcast_update({
                        "account_no": account["account_no"],
                        "status": "error",
                        "message": error_msg
                    })
                return result

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
