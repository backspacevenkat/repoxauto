import logging
import os
from typing import Dict, Optional, List
from datetime import datetime, timezone
import asyncio

logger = logging.getLogger(__name__)

class DirectMessageOperations:
    def __init__(self, http_client):
        """Initialize DirectMessageOperations with HTTP client"""
        self.http_client = http_client

    async def send_dm(
        self,
        recipient_id: str,
        text: str,
        media: Optional[str] = None
    ) -> Dict:
        """Send a direct message with optional media"""
        logger.info(f"Sending DM to user {recipient_id}")
        try:
            # If recipient_id is username, get the numeric ID
            if not recipient_id.isdigit():
                recipient_id = await self._get_user_id(recipient_id)

            # Extract sender ID from OAuth token
            sender_id = None
            if self.http_client.access_token and "-" in self.http_client.access_token:
                sender_id = self.http_client.access_token.split("-")[0]
            if not sender_id:
                raise Exception("Could not extract sender ID from access_token")

            # Create conversation ID (sorted user IDs joined by dash)
            user_ids = sorted([int(sender_id), int(recipient_id)])
            conversation_id = f"{user_ids[0]}-{user_ids[1]}"

            # Check DM permissions
            await self._check_dm_permissions(recipient_id)

            # Handle media upload if provided
            media_id = None
            if media:
                media_id = await self._handle_media_upload(media)

            # Prepare DM request
            dm_params = {
                "cards_platform": "Web-12",
                "include_cards": "1",
                "include_quote_count": "true",
                "include_reply_count": "1",
                "dm_users": "false",
                "include_groups": "true",
                "include_inbox_timelines": "true",
                "include_ext_media_color": "true",
                "supports_reactions": "true",
                "include_ext_edit_control": "true",
            }

            form_data = {
                "conversation_id": conversation_id,
                "text": text,
            }

            if media_id:
                form_data["media_id"] = media_id

            headers = {
                **self.http_client.headers,
                "content-type": "application/x-www-form-urlencoded",
                "referer": f"https://twitter.com/messages/{recipient_id}",
            }

            response = await self.http_client.make_request(
                method="POST",
                url="https://twitter.com/i/api/1.1/dm/new.json",
                params=dm_params,
                data=form_data,
                headers=headers
            )

            # Handle response
            if response and "event" in response:
                return {
                    "success": True,
                    "recipient_id": recipient_id,
                    "message_id": response["event"].get("id"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "conversation_id": conversation_id
                }
            elif response and 'entries' in response and len(response['entries']) > 0:
                message_entry = response['entries'][0].get('message', {})
                message_id = message_entry.get('id')
                if message_id:
                    return {
                        "success": True,
                        "recipient_id": recipient_id,
                        "message_id": message_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "conversation_id": conversation_id
                    }

            logger.error(f"Unexpected DM response format: {response}")
            return {
                "success": False,
                "error": "Invalid response format"
            }

        except Exception as e:
            logger.error(f"Error sending DM to {recipient_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _get_user_id(self, username: str) -> str:
        """Get user ID from username"""
        try:
            variables = {
                "screen_name": username,
                "withSafetyModeUserFields": True
            }

            response = await self.http_client.graphql_request('UserByScreenName', variables)
            user_data = response.get('data', {}).get('user', {})
            
            if not user_data:
                raise Exception(f"User {username} not found")

            result = user_data.get('result', {})
            user_id = result.get('rest_id')
            
            if not user_id:
                raise Exception(f"Could not get ID for user {username}")

            return user_id

        except Exception as e:
            logger.error(f"Error getting user ID: {str(e)}")
            raise

    async def _check_dm_permissions(self, recipient_id: str):
        """Check if we can send DMs to the user"""
        try:
            perms_url = "https://twitter.com/i/api/1.1/dm/permissions.json"
            perms_params = {
                "recipient_ids": recipient_id,
                "dm_users": "true"
            }

            response = await self.http_client.make_request(
                method="GET",
                url=perms_url,
                params=perms_params
            )

            if not response:
                raise Exception("Failed to check DM permissions")

            # Check if user allows DMs
            if not response.get('can_dm', True):
                raise Exception("User does not accept DMs")

        except Exception as e:
            logger.error(f"Error checking DM permissions: {str(e)}")
            raise

    async def _handle_media_upload(self, media_path: str) -> Optional[str]:
        """Handle media upload for DMs"""
        try:
            found_path = None
            possible_paths = [
                os.path.join('backend/media', os.path.basename(media_path)),
                os.path.join('backend/media', media_path),
                media_path
            ]

            for path in possible_paths:
                if os.path.exists(path):
                    found_path = path
                    break

            if not found_path:
                raise Exception(f"Media file not found: {media_path}")

            # Upload media with DM category
            media_ids = await self.http_client.upload_media([found_path], for_dm=True)
            
            if not media_ids:
                raise Exception("Failed to upload media")

            return media_ids[0]

        except Exception as e:
            logger.error(f"Error handling media upload: {str(e)}")
            raise

    async def get_conversation(
        self,
        user_id: str,
        count: int = 50,
        cursor: Optional[str] = None
    ) -> Dict:
        """Get DM conversation with a user"""
        logger.info(f"Getting conversation with user {user_id}")
        try:
            # Get numeric user ID if username provided
            if not user_id.isdigit():
                user_id = await self._get_user_id(user_id)

            # Get sender ID from OAuth token
            sender_id = None
            if self.http_client.access_token and "-" in self.http_client.access_token:
                sender_id = self.http_client.access_token.split("-")[0]
            if not sender_id:
                raise Exception("Could not extract sender ID from access_token")

            # Create conversation ID
            user_ids = sorted([int(sender_id), int(user_id)])
            conversation_id = f"{user_ids[0]}-{user_ids[1]}"

            params = {
                "context": "FETCH_DM_CONVERSATION",
                "include_profile_interstitial_type": "1",
                "include_blocking": "1",
                "include_blocked_by": "1",
                "include_followed_by": "1",
                "include_want_retweets": "1",
                "include_mute_edge": "1",
                "include_can_dm": "1",
                "include_can_media_tag": "1",
                "skip_status": "1",
                "cursor": cursor,
                "count": count,
                "include_cards": "1",
                "include_ext_alt_text": "true",
                "include_quote_count": "true",
                "include_reply_count": "1",
                "tweet_mode": "extended",
                "include_groups": "true",
                "include_inbox_timelines": "true",
                "include_ext_media_color": "true",
                "supports_reactions": "true",
                "include_conversation_info": "true"
            }

            response = await self.http_client.make_request(
                method="GET",
                url=f"https://twitter.com/i/api/1.1/dm/conversation/{conversation_id}.json",
                params=params
            )

            if not response:
                raise Exception("Failed to get conversation")

            messages = []
            next_cursor = None

            # Process messages
            for entry in response.get('entries', []):
                message = entry.get('message', {})
                if message:
                    processed_message = {
                        'id': message.get('id'),
                        'text': message.get('text'),
                        'sender_id': message.get('sender_id'),
                        'recipient_id': message.get('recipient_id'),
                        'created_at': message.get('created_at'),
                        'media': self._process_message_media(message)
                    }
                    messages.append(processed_message)

            # Get pagination cursor
            if response.get('next_cursor'):
                next_cursor = response['next_cursor']

            return {
                'success': True,
                'conversation_id': conversation_id,
                'messages': messages,
                'next_cursor': next_cursor,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error getting conversation: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    def _process_message_media(self, message: Dict) -> List[Dict]:
        """Process media attachments in a message"""
        media = []
        
        for attachment in message.get('attachment', []):
            media_entity = attachment.get('media', {})
            if media_entity:
                media_item = {
                    'type': media_entity.get('type'),
                    'url': media_entity.get('media_url_https'),
                    'alt_text': media_entity.get('ext_alt_text')
                }

                # Handle video variants
                if media_item['type'] in ['video', 'animated_gif']:
                    variants = media_entity.get('video_info', {}).get('variants', [])
                    if variants:
                        video_variants = [v for v in variants if v.get('content_type') == 'video/mp4']
                        if video_variants:
                            highest_bitrate = max(video_variants, key=lambda x: x.get('bitrate', 0))
                            media_item['video_url'] = highest_bitrate['url']
                            media_item['duration_ms'] = media_entity.get('video_info', {}).get('duration_millis')

                media.append(media_item)

        return media