import hmac
import hashlib
import base64
import random
import string
import time
import logging
from typing import Dict, Optional
from urllib.parse import quote, urlparse

logger = logging.getLogger(__name__)

def generate_nonce(length: int = 32) -> str:
    """
    Generate a random nonce string for OAuth requests
    Args:
        length: Length of the nonce string
    Returns:
        Random string of specified length
    """
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(length))

def construct_proxy_url(username: str, password: str, host: str, port: str) -> str:
    """
    Construct a proxy URL with proper encoding
    Args:
        username: Proxy username
        password: Proxy password
        host: Proxy host
        port: Proxy port
    Returns:
        Properly formatted proxy URL
    """
    try:
        encoded_username = quote(str(username), safe='')
        encoded_password = quote(str(password), safe='')
        proxy_url = f"http://{encoded_username}:{encoded_password}@{host}:{port}"
        
        # Validate the constructed URL
        parsed = urlparse(proxy_url)
        if not all([parsed.scheme, parsed.hostname, parsed.port]):
            raise ValueError("Invalid proxy URL components")
            
        return proxy_url
    except Exception as e:
        logger.error(f"Error constructing proxy URL: {str(e)}")
        raise

def generate_oauth_signature(
    method: str,
    url: str,
    params: Dict[str, str],
    consumer_secret: str,
    access_token_secret: str
) -> str:
    """
    Generate OAuth 1.0a signature
    Args:
        method: HTTP method (GET, POST, etc.)
        url: Request URL
        params: OAuth parameters and request parameters
        consumer_secret: OAuth consumer secret
        access_token_secret: OAuth access token secret
    Returns:
        OAuth signature
    """
    try:
        # Ensure all values are strings
        params = {str(k): str(v) for k, v in params.items()}
        
        # Create parameter string - must be sorted
        sorted_params = sorted(params.items())
        param_string = '&'.join([
            f"{quote(k, safe='')}"
            f"="
            f"{quote(v, safe='')}"
            for k, v in sorted_params
        ])

        # Create signature base string
        signature_base = '&'.join([
            quote(method.upper(), safe=''),
            quote(url, safe=''),
            quote(param_string, safe='')
        ])

        # Create signing key
        signing_key = f"{quote(str(consumer_secret), safe='')}&{quote(str(access_token_secret or ''), safe='')}"

        # Calculate HMAC-SHA1 signature
        hashed = hmac.new(
            signing_key.encode('utf-8'),
            signature_base.encode('utf-8'),
            hashlib.sha1
        )

        return base64.b64encode(hashed.digest()).decode('utf-8')
    except Exception as e:
        logger.error(f"Error generating OAuth signature: {str(e)}")
        raise

def get_oauth_params(
    consumer_key: str,
    access_token: Optional[str] = None,
    include_token: bool = True
) -> Dict[str, str]:
    """
    Get basic OAuth parameters
    Args:
        consumer_key: OAuth consumer key
        access_token: OAuth access token
        include_token: Whether to include the access token in parameters
    Returns:
        Dictionary of OAuth parameters
    """
    params = {
        'oauth_consumer_key': consumer_key,
        'oauth_nonce': generate_nonce(),
        'oauth_signature_method': 'HMAC-SHA1',
        'oauth_timestamp': str(int(time.time())),
        'oauth_version': '1.0'
    }
    
    if include_token and access_token:
        params['oauth_token'] = access_token
        
    return params

def create_oauth_header(params: Dict[str, str]) -> str:
    """
    Create OAuth Authorization header from parameters
    Args:
        params: OAuth parameters including signature
    Returns:
        Formatted OAuth header string
    """
    return 'OAuth ' + ', '.join([
        f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
        for k, v in sorted(params.items())
    ])

def sign_request(
    method: str,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    access_token: Optional[str] = None,
    access_token_secret: Optional[str] = None,
    additional_params: Optional[Dict[str, str]] = None,
    include_token: bool = True
) -> str:
    """
    Sign a request with OAuth 1.0a
    Args:
        method: HTTP method
        url: Request URL
        consumer_key: OAuth consumer key
        consumer_secret: OAuth consumer secret
        access_token: OAuth access token
        access_token_secret: OAuth access token secret
        additional_params: Additional parameters to include in signature
        include_token: Whether to include access token
    Returns:
        OAuth Authorization header
    """
    try:
        # Get base OAuth params
        oauth_params = get_oauth_params(consumer_key, access_token, include_token)
        
        # Combine with additional params for signature
        all_params = oauth_params.copy()
        if additional_params:
            all_params.update(additional_params)
            
        # Generate signature
        signature = generate_oauth_signature(
            method,
            url,
            all_params,
            consumer_secret,
            access_token_secret
        )
        
        # Add signature to OAuth params
        oauth_params['oauth_signature'] = signature
        
        # Create Authorization header
        return create_oauth_header(oauth_params)
    except Exception as e:
        logger.error(f"Error signing request: {str(e)}")
        raise

def validate_tokens(
    consumer_key: Optional[str],
    consumer_secret: Optional[str],
    access_token: Optional[str],
    access_token_secret: Optional[str]
) -> bool:
    """
    Validate that OAuth tokens are properly formatted
    Args:
        consumer_key: OAuth consumer key
        consumer_secret: OAuth consumer secret
        access_token: OAuth access token
        access_token_secret: OAuth access token secret
    Returns:
        True if tokens are valid, False otherwise
    """
    # Check that required tokens are present and non-empty
    if not all([consumer_key, consumer_secret]):
        logger.error("Missing required consumer credentials")
        return False
        
    # If access token is provided, secret must also be present
    if access_token and not access_token_secret:
        logger.error("Access token provided without secret")
        return False
        
    # Check token formats
    try:
        for token in [consumer_key, consumer_secret, access_token, access_token_secret]:
            if token and not isinstance(token, str):
                logger.error(f"Invalid token format: {token}")
                return False
                
        return True
    except Exception as e:
        logger.error(f"Error validating tokens: {str(e)}")
        return False