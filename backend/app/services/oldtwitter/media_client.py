import os
import logging
import mimetypes
import asyncio
from typing import List, Dict, Optional

from .base_client import BaseTwitterClient
from .types import API_ENDPOINTS

logger = logging.getLogger(__name__)

class MediaClient(BaseTwitterClient):
    async def upload_media(self, media_paths: List[str], for_dm: bool = False) -> List[str]:
        """Upload media files using chunked upload endpoint"""
        logger.info(f"Uploading {len(media_paths)} media files")
        media_ids = []
        
        for media_path in media_paths:
            try:
                if not os.path.exists(media_path):
                    logger.error(f"Media file not found: {media_path}")
                    continue

                file_size = os.path.getsize(media_path)
                mime_type = mimetypes.guess_type(media_path)[0] or 'application/octet-stream'
                
                # Use appropriate media category based on type and context
                if mime_type.startswith('image/'):
                    if for_dm:
                        media_category = 'dm_gif' if mime_type == 'image/gif' else 'dm_image'
                    else:
                        media_category = 'tweet_gif' if mime_type == 'image/gif' else 'tweet_image'
                elif mime_type.startswith('video/'):
                    media_category = 'dm_video' if for_dm else 'tweet_video'
                else:
                    media_category = 'dm_image' if for_dm else 'tweet_image'

                logger.info(f"Starting upload for {media_path} ({mime_type} -> {media_category})")

                # INIT phase
                init_data = {
                    'command': 'INIT',
                    'total_bytes': str(file_size),
                    'media_type': mime_type,
                    'media_category': media_category
                }

                init_response = await self._make_request(
                    method="POST",
                    url=API_ENDPOINTS['upload'],
                    data=init_data
                )
                
                if not init_response or 'media_id_string' not in init_response:
                    logger.error("No media_id in INIT response")
                    continue

                media_id = init_response['media_id_string']
                logger.info(f"INIT successful: {media_id}")

                # APPEND phase
                with open(media_path, 'rb') as f:
                    chunk = f.read()

                append_data = {
                    'command': 'APPEND',
                    'media_id': media_id,
                    'segment_index': '0'
                }

                # Format multipart data
                files = {
                    'media': ('blob', chunk, mime_type)
                }

                append_response = await self._make_request(
                    method="POST",
                    url=API_ENDPOINTS['upload'],
                    data=append_data,
                    files=files
                )

                if append_response is None:
                    logger.error("APPEND failed")
                    continue

                logger.info("APPEND successful")

                # FINALIZE phase
                finalize_data = {
                    'command': 'FINALIZE',
                    'media_id': media_id
                }

                finalize_response = await self._make_request(
                    method="POST",
                    url=API_ENDPOINTS['upload'],
                    data=finalize_data
                )

                if not finalize_response:
                    logger.error("FINALIZE failed")
                    continue

                # For videos/GIFs, we need to wait for processing
                if mime_type in ['video/mp4', 'video/quicktime', 'image/gif']:
                    await self._poll_media_status(media_id)

                media_ids.append(media_id)
                logger.info(f"Successfully uploaded {media_path} as {media_id}")

            except Exception as e:
                logger.error(f"Error uploading {media_path}: {str(e)}")
                continue

        return media_ids

    async def _poll_media_status(self, media_id: str, max_attempts: int = 10):
        """Poll for media processing status"""
        logger.info(f"Polling status for media {media_id}")
        
        for attempt in range(max_attempts):
            try:
                status_data = {
                    'command': 'STATUS',
                    'media_id': media_id
                }
                
                response = await self._make_request(
                    method="GET",
                    url=API_ENDPOINTS['upload'],
                    params=status_data
                )

                if not response:
                    logger.error("No status response")
                    await asyncio.sleep(2)
                    continue

                processing_info = response.get('processing_info', {})
                if not processing_info:
                    logger.info("No processing_info, media ready")
                    return

                state = processing_info.get('state')
                logger.info(f"Media {media_id} processing state: {state}")

                if state == 'succeeded':
                    logger.info(f"Media {media_id} processing complete")
                    return
                elif state == 'failed':
                    error = processing_info.get('error', {})
                    logger.error(f"Media processing failed: {error}")
                    raise Exception(f"Media processing failed: {error}")
                else:
                    check_after = processing_info.get('check_after_secs', 5)
                    logger.info(f"Waiting {check_after}s before next check")
                    await asyncio.sleep(check_after)

            except Exception as e:
                logger.error(f"Error polling media status: {str(e)}")
                await asyncio.sleep(2)

        raise Exception(f"Media processing timed out after {max_attempts} attempts")

    def get_media_info(self, file_path: str) -> Dict:
        """Get media file information"""
        content_type = mimetypes.guess_type(file_path)[0]
        file_size = os.path.getsize(file_path)
        category_map = {
            'image/jpeg': 'tweet_image',
            'image/png': 'tweet_image',
            'image/gif': 'tweet_gif',
            'video/mp4': 'tweet_video',
            'video/quicktime': 'tweet_video'
        }
        return {
            'file_size': file_size,
            'content_type': content_type,
            'category': category_map.get(content_type)
        }
