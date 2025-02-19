import logging
import os
import mimetypes
import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class MediaOperations:
    def __init__(self, http_client):
        """Initialize MediaOperations with HTTP client"""
        self.http_client = http_client
        self.CHUNK_SIZE = 4 * 1024 * 1024  # 4MB chunks

    async def upload_media(
        self,
        media_paths: List[str],
        for_dm: bool = False
    ) -> List[str]:
        """Upload media files and return media IDs"""
        logger.info(f"Uploading {len(media_paths)} media files")
        media_ids = []
        
        for media_path in media_paths:
            try:
                if not os.path.exists(media_path):
                    # Try different path combinations
                    possible_paths = [
                        os.path.join('backend/media', os.path.basename(media_path)),
                        os.path.join('backend/media', media_path),
                        media_path
                    ]
                    
                    found_path = None
                    for path in possible_paths:
                        if os.path.exists(path):
                            found_path = path
                            break
                    
                    if not found_path:
                        logger.error(f"Media file not found. Tried: {', '.join(possible_paths)}")
                        continue
                        
                    media_path = found_path

                # Get media information
                media_info = self.get_media_info(media_path)
                if not media_info:
                    logger.error(f"Could not determine media type for {media_path}")
                    continue

                file_size = media_info['file_size']
                mime_type = media_info['content_type']
                category = self.get_media_category(mime_type, for_dm)

                if file_size > self.CHUNK_SIZE:
                    # Use chunked upload for large files
                    media_id = await self.upload_chunked_media(
                        media_path,
                        mime_type,
                        file_size,
                        category
                    )
                else:
                    # Use single request upload for small files
                    media_id = await self.upload_single_media(
                        media_path,
                        mime_type,
                        category
                    )

                if media_id:
                    media_ids.append(media_id)
                    logger.info(f"Successfully uploaded {media_path}")
                await asyncio.sleep(1)  # Small delay between uploads

            except Exception as e:
                logger.error(f"Error uploading {media_path}: {str(e)}")
                continue

        return media_ids

    def get_media_info(self, file_path: str) -> Optional[Dict]:
        """Get media file information"""
        try:
            content_type = mimetypes.guess_type(file_path)[0]
            if not content_type:
                logger.error(f"Could not determine content type for {file_path}")
                return None

            file_size = os.path.getsize(file_path)
            
            return {
                'file_size': file_size,
                'content_type': content_type
            }
        except Exception as e:
            logger.error(f"Error getting media info: {str(e)}")
            return None

    def get_media_category(self, mime_type: str, for_dm: bool = False) -> str:
        """Determine media category based on MIME type and context"""
        base_type = mime_type.split('/')[0]
        sub_type = mime_type.split('/')[1] if '/' in mime_type else ''
        
        if base_type == 'image':
            if sub_type == 'gif':
                return 'dm_gif' if for_dm else 'tweet_gif'
            return 'dm_image' if for_dm else 'tweet_image'
        elif base_type == 'video':
            return 'dm_video' if for_dm else 'tweet_video'
        else:
            return 'dm_image' if for_dm else 'tweet_image'

    async def upload_single_media(
        self,
        media_path: str,
        mime_type: str,
        category: str
    ) -> Optional[str]:
        """Upload media file in a single request"""
        try:
            with open(media_path, 'rb') as file:
                media_data = file.read()

            files = {
                'media': ('media', media_data, mime_type)
            }
            
            data = {
                'media_category': category
            }

            response = await self.http_client.make_request(
                method="POST",
                url="https://upload.twitter.com/1.1/media/upload.json",
                files=files,
                data=data
            )

            if response and 'media_id_string' in response:
                return response['media_id_string']
            
            logger.error(f"Failed to upload media: {response}")
            return None

        except Exception as e:
            logger.error(f"Error in single media upload: {str(e)}")
            return None

    async def upload_chunked_media(
        self,
        media_path: str,
        mime_type: str,
        file_size: int,
        category: str
    ) -> Optional[str]:
        """Upload large media file in chunks"""
        try:
            # INIT phase
            init_data = {
                'command': 'INIT',
                'total_bytes': str(file_size),
                'media_type': mime_type,
                'media_category': category
            }

            init_response = await self.http_client.make_request(
                method="POST",
                url="https://upload.twitter.com/1.1/media/upload.json",
                data=init_data
            )

            if not init_response or 'media_id_string' not in init_response:
                logger.error("Failed to initialize chunked upload")
                return None

            media_id = init_response['media_id_string']

            # APPEND phase
            with open(media_path, 'rb') as file:
                segment_index = 0
                while True:
                    chunk = file.read(self.CHUNK_SIZE)
                    if not chunk:
                        break

                    append_data = {
                        'command': 'APPEND',
                        'media_id': media_id,
                        'segment_index': str(segment_index)
                    }

                    files = {
                        'media': ('media', chunk, mime_type)
                    }

                    append_response = await self.http_client.make_request(
                        method="POST",
                        url="https://upload.twitter.com/1.1/media/upload.json",
                        data=append_data,
                        files=files
                    )

                    if append_response is None:
                        logger.error(f"Failed to upload chunk {segment_index}")
                        return None

                    segment_index += 1

            # FINALIZE phase
            finalize_data = {
                'command': 'FINALIZE',
                'media_id': media_id
            }

            finalize_response = await self.http_client.make_request(
                method="POST",
                url="https://upload.twitter.com/1.1/media/upload.json",
                data=finalize_data
            )

            if not finalize_response:
                logger.error("Failed to finalize media upload")
                return None

            # Handle video/gif processing
            if mime_type.startswith(('video/', 'image/gif')):
                await self._wait_for_processing(media_id)

            return media_id

        except Exception as e:
            logger.error(f"Error in chunked media upload: {str(e)}")
            return None

    async def _wait_for_processing(self, media_id: str, max_attempts: int = 10) -> bool:
        """Wait for media processing to complete"""
        attempt = 0
        while attempt < max_attempts:
            try:
                status_response = await self.http_client.make_request(
                    method="GET",
                    url="https://upload.twitter.com/1.1/media/upload.json",
                    params={
                        'command': 'STATUS',
                        'media_id': media_id
                    }
                )

                if not status_response:
                    logger.error("Failed to get media status")
                    return False

                processing_info = status_response.get('processing_info', {})
                state = processing_info.get('state')

                if state == 'succeeded':
                    return True
                elif state == 'failed':
                    error = processing_info.get('error', {})
                    logger.error(f"Media processing failed: {error}")
                    return False
                
                check_after_secs = processing_info.get('check_after_secs', 5)
                await asyncio.sleep(check_after_secs)
                attempt += 1

            except Exception as e:
                logger.error(f"Error checking media status: {str(e)}")
                return False

        logger.error("Media processing timed out")
        return False

    async def get_media_metadata(self, media_id: str) -> Optional[Dict]:
        """Get metadata for uploaded media"""
        try:
            response = await self.http_client.make_request(
                method="GET",
                url="https://upload.twitter.com/1.1/media/upload.json",
                params={
                    'command': 'STATUS',
                    'media_id': media_id
                }
            )

            if response:
                return {
                    'media_id': media_id,
                    'expires_after_secs': response.get('expires_after_secs'),
                    'processing_info': response.get('processing_info', {}),
                    'type': response.get('type'),
                    'size': response.get('size'),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }

            return None

        except Exception as e:
            logger.error(f"Error getting media metadata: {str(e)}")
            return None