import os
import mimetypes
import logging
import asyncio
from typing import List, Dict, Optional
from urllib.parse import quote
import time
import hmac
import hashlib
import base64

logger = logging.getLogger(__name__)

def generate_nonce(length: int = 32) -> str:
    """Generate a random nonce string"""
    import string
    import random
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(length))

def generate_oauth_signature(
    method: str,
    url: str,
    params: Dict[str, str],
    consumer_secret: str,
    access_token_secret: str
) -> str:
    """Generate OAuth 1.0a signature"""
    # Sort parameters
    sorted_params = sorted(params.items())
    param_string = '&'.join(
        f"{quote(str(k), safe='')}={quote(str(v), safe='')}"
        for k, v in sorted_params
    )
    
    # Create signature base string
    signature_base = '&'.join([
        quote(method.upper(), safe=''),
        quote(url, safe=''),
        quote(param_string, safe='')
    ])
    
    # Create signing key
    signing_key = f"{quote(consumer_secret, safe='')}&{quote(access_token_secret, safe='')}"
    
    # Calculate HMAC-SHA1 signature
    hashed = hmac.new(
        signing_key.encode('utf-8'),
        signature_base.encode('utf-8'),
        hashlib.sha1
    )
    
    return base64.b64encode(hashed.digest()).decode('utf-8')

class MediaUploader:
    def __init__(self, client):
        self.client = client
        self.upload_url = "https://upload.twitter.com/1.1/media/upload.json"

    def _get_oauth_params(self) -> Dict[str, str]:
        """Get base OAuth parameters without signature"""
        return {
            'oauth_consumer_key': self.client.consumer_key,
            'oauth_nonce': generate_nonce(),
            'oauth_signature_method': 'HMAC-SHA1',
            'oauth_timestamp': str(int(time.time())),
            'oauth_token': self.client.access_token,
            'oauth_version': '1.0'
        }

    def _get_auth_header(self, method: str, params: Dict[str, str]) -> str:
        """Create Authorization header with OAuth signature"""
        # Get base OAuth params
        oauth_params = self._get_oauth_params()
        
        # Generate signature
        signature = generate_oauth_signature(
            method,
            self.upload_url,
            {**oauth_params, **params},  # Include all params in signature
            self.client.consumer_secret,
            self.client.access_token_secret
        )
        oauth_params['oauth_signature'] = signature
        
        # Create Authorization header
        return 'OAuth ' + ', '.join(
            f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
            for k, v in sorted(oauth_params.items())
        )

    async def upload_media(self, media_paths: List[str]) -> List[str]:
        """Upload media files using chunked upload"""
        media_ids = []
        
        for media_path in media_paths:
            try:
                if not os.path.exists(media_path):
                    logger.error(f"Media file not found: {media_path}")
                    continue

                file_size = os.path.getsize(media_path)
                mime_type = mimetypes.guess_type(media_path)[0] or 'application/octet-stream'

                # Determine media category
                if mime_type.startswith("image/"):
                    media_category = "tweet_image"
                    if mime_type == "image/gif":
                        media_category = "tweet_gif"
                elif mime_type.startswith("video/"):
                    media_category = "tweet_video"
                else:
                    media_category = "tweet_image"  # Default to image

                logger.info(f"Starting upload for {media_path} ({mime_type} -> {media_category})")

                # INIT phase
                init_params = {
                    'command': 'INIT',
                    'total_bytes': str(file_size),
                    'media_type': mime_type,
                    'media_category': media_category
                }
                
                auth_header = self._get_auth_header('POST', init_params)
                
                init_response = await self.client._raw_post(
                    url=self.upload_url,
                    data=init_params,
                    headers={
                        'Authorization': auth_header,
                        'Content-Type': 'application/x-www-form-urlencoded'
                    }
                )

                if not init_response or 'media_id_string' not in init_response:
                    logger.error(f"INIT failed: {init_response}")
                    continue

                media_id = init_response['media_id_string']
                logger.info(f"INIT successful: {media_id}")

                # APPEND phase
                with open(media_path, 'rb') as f:
                    file_data = f.read()

                append_params = {
                    'command': 'APPEND',
                    'media_id': media_id,
                    'segment_index': '0'
                }
                
                auth_header = self._get_auth_header('POST', append_params)
                
                append_response = await self.client._raw_post(
                    url=self.upload_url,
                    params=append_params,
                    files={
                        'media': ('blob', file_data, mime_type)
                    },
                    headers={
                        'Authorization': auth_header
                    }
                )

                # Twitter returns 204 No Content for successful APPEND
                if append_response != {}:
                    logger.error(f"APPEND failed: {append_response}")
                    continue

                logger.info(f"APPEND successful for {media_id}")

                # FINALIZE phase
                finalize_params = {
                    'command': 'FINALIZE',
                    'media_id': media_id
                }
                
                auth_header = self._get_auth_header('POST', finalize_params)
                
                finalize_response = await self.client._raw_post(
                    url=self.upload_url,
                    data=finalize_params,
                    headers={
                        'Authorization': auth_header,
                        'Content-Type': 'application/x-www-form-urlencoded'
                    }
                )

                if not finalize_response:
                    logger.error("FINALIZE failed with empty response")
                    continue

                # Handle async processing for videos/GIFs
                if 'processing_info' in finalize_response:
                    logger.info(f"Media {media_id} requires processing")
                    processing_info = finalize_response.get('processing_info', {})
                    
                    while processing_info.get('state') == 'pending':
                        check_after_secs = processing_info.get('check_after_secs', 1)
                        await asyncio.sleep(check_after_secs)
                        
                        status_params = {
                            'command': 'STATUS',
                            'media_id': media_id
                        }
                        
                        auth_header = self._get_auth_header('GET', status_params)
                        
                        status_response = await self.client._raw_post(
                            url=self.upload_url,
                            params=status_params,
                            headers={
                                'Authorization': auth_header
                            }
                        )
                        
                        if not status_response:
                            logger.error("Failed to get processing status")
                            break
                        
                        processing_info = status_response.get('processing_info', {})
                        if processing_info.get('state') == 'failed':
                            logger.error(f"Processing failed: {processing_info.get('error')}")
                            break
                        elif processing_info.get('state') == 'succeeded':
                            logger.info(f"Processing completed for {media_id}")
                            break

                media_ids.append(media_id)
                logger.info(f"Successfully uploaded {media_path} as {media_id}")

            except Exception as e:
                logger.error(f"Error uploading {media_path}: {str(e)}")
                continue

        return media_ids
