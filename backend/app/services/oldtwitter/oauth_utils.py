import hmac
import hashlib
import base64
import random
import string
import time
from typing import Dict
from urllib.parse import quote

def generate_nonce(length: int = 32) -> str:
    """Generate a random nonce string"""
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(length))

def generate_oauth_signature(
    method: str,
    url: str,
    params: Dict[str, str],
    consumer_secret: str,
    access_token_secret: str
) -> str:
    """Generate OAuth 1.0a signature"""
    # Ensure all values are strings
    params = {str(k): str(v) for k, v in params.items()}
    
    # Create parameter string
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

def construct_proxy_url(username: str, password: str, host: str, port: str) -> str:
    """Construct a proxy URL with proper encoding"""
    encoded_username = quote(str(username), safe='')
    encoded_password = quote(str(password), safe='')
    return f"http://{encoded_username}:{encoded_password}@{host}:{port}"

def create_oauth_params(consumer_key: str, access_token: str) -> Dict[str, str]:
    """Create basic OAuth parameters"""
    return {
        'oauth_consumer_key': consumer_key,
        'oauth_nonce': generate_nonce(),
        'oauth_signature_method': 'HMAC-SHA1',
        'oauth_timestamp': str(int(time.time())),
        'oauth_token': access_token,
        'oauth_version': '1.0'
    }

def create_auth_header(oauth_params: Dict[str, str]) -> str:
    """Create Authorization header from OAuth parameters"""
    return 'OAuth ' + ', '.join(
        f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
        for k, v in sorted(oauth_params.items())
    )
