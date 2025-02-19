import logging
import os
from typing import Dict, Optional
from datetime import datetime, timezone

from .base_client import BaseTwitterClient
from .media_client import MediaClient
from .user_client import UserClient
from .types import API_ENDPOINTS

logger = logging.getLogger(__name__)

class DMClient(BaseTwitterClient):
    async def send_dm(
        self,
        recipient_id: str,
        text: str,
        media: Optional[str] = None
    ) -> Dict:
        """Send a direct message"""
        logger.info(f"Sending DM to user {recipient_id}")
        try:
            # If recipient_id is a username, get the numeric ID
            if not recipient_id.isdigit():
                user_client = UserClient(
                    account_no=self.account_no,
                    auth_token=self.auth_token,
                    ct0=self.ct0,
                    consumer_key=self.consumer_key,
                    consumer_secret=self.consumer_secret,
                    access_token=self.access_token,
                    access_token_secret=self.access_token_secret,
                    proxy_config=self.proxy_config
                )
                recipient_id = await user_client.get_user_id(recipient_id)

            # Get sender ID from access token
            sender_id = None
            if self.access_token and "-" in self.access_token:
                sender_id = self.access_token.split("-")[0]
            if not sender_id:
                raise Exception("Could not extract sender ID from access token")

            # Build conversation ID (sorted user IDs joined by dash)
            user_ids = sorted([int(sender_id), int(recipient_id)])
            conversation_id = f"{user_ids[0]}-{user_ids[1]}"

            # Check DM permissions
            try:
                await self._make_request(
                    method="GET",
                    url=API_ENDPOINTS['dm_lookup'],
                    params={
                        "recipient_ids": recipient_id,
                        "dm_users": "true"
                    },
                    headers={
                        **self.graphql_headers,
                        "referer": "https://twitter.com/messages"
                    }
                )
            except Exception as e:
                logger.warning(f"DM permissions check failed (may be harmless): {e}")

            # Handle media upload if provided
            media_id = None
            if media:
                media_client = MediaClient(
                    account_no=self.account_no,
                    auth_token=self.auth_token,
                    ct0=self.ct0,
                    consumer_key=self.consumer_key,
                    consumer_secret=self.consumer_secret,
                    access_token=self.access_token,
                    access_token_secret=self.access_token_secret,
                    proxy_config=self.proxy_config
                )

                # Find media file
                found_path = None
                possible_paths = [
                    os.path.join(os.getcwd(), media),
                    os.path.join(os.getcwd(), 'backend', media),
                    media
                ]
                
                for path in possible_paths:
                    if os.path.exists(path):
                        found_path = path
                        break
                
                if found_path:
                    # Upload with DM-specific media category
                    media_ids = await media_client.upload_media([found_path], for_dm=True)
                    if media_ids:
                        media_id = media_ids[0]
                else:
                    logger.error(f"Media file not found: {media}")

            # Set up form data
            form_data = {
                "conversation_id": conversation_id,
                "text": text
            }
            if media_id:
                form_data["media_id"] = media_id

            # Send the DM
            response = await self._make_request(
                method="POST",
                url=API_ENDPOINTS['dm_new'],
                params={
                    "cards_platform": "Web-12",
                    "include_cards": "1",
                    "include_quote_count": "true",
                    "include_reply_count": "1",
                    "dm_users": "false",
                    "include_groups": "true",
                    "include_inbox_timelines": "true",
                    "include_ext_media_color": "true",
                    "supports_reactions": "true",
                    "include_ext_edit_control": "true"
                },
                data=form_data,
                headers={
                    **self.graphql_headers,
                    "referer": f"https://twitter.com/messages/{recipient_id}",
                    "content-type": "application/x-www-form-urlencoded"
                }
            )

            # Handle response
            if response and "event" in response:
                logger.info(f"Successfully sent DM to {recipient_id} (ID: {response['event'].get('id')})")
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
                    logger.info(f"Successfully sent DM to {recipient_id} (ID: {message_id})")
                    return {
                        "success": True,
                        "recipient_id": recipient_id,
                        "message_id": message_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "conversation_id": conversation_id
                    }

            logger.error(f"Failed to send DM - response: {response}")
            if "errors" in response and response["errors"]:
                error_message = response["errors"][0].get("message", "Unknown error")
                return {
                    "success": False,
                    "error": error_message
                }
            return {
                "success": False,
                "error": "DM endpoint returned unexpected structure"
            }

        except Exception as e:
            logger.error(f"Error sending DM to {recipient_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _check_dm_permissions(self, recipient_id: str) -> bool:
        """Check if we can send DMs to a user"""
        try:
            response = await self._make_request(
                method="GET",
                url=API_ENDPOINTS['dm_lookup'],
                params={
                    "recipient_ids": recipient_id,
                    "dm_users": "true"
                }
            )
            return bool(response and not response.get('errors'))
        except Exception as e:
            logger.warning(f"Error checking DM permissions: {e}")
            return False
