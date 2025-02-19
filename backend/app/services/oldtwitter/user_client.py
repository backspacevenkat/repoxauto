import logging
import random
import asyncio
from typing import Dict, Optional
from datetime import datetime, timezone

from .base_client import BaseTwitterClient
from .types import (
    UserResponse, GRAPHQL_ENDPOINTS,
    DEFAULT_FEATURES, API_ENDPOINTS
)

logger = logging.getLogger(__name__)

class UserClient(BaseTwitterClient):
    async def get_user_id(self, username: str) -> str:
        """Get user ID from username using GraphQL"""
        logger.info(f"Getting user ID for {username}")
        try:
            variables = {
                "screen_name": username,
                "withSafetyModeUserFields": True,
                "withHighlightedLabel": True
            }

            features = DEFAULT_FEATURES.copy()
            features.update({
                "hidden_profile_likes_enabled": True,
                "hidden_profile_subscriptions_enabled": True,
                "responsive_web_graphql_exclude_directive_enabled": True,
                "verified_phone_label_enabled": False,
                "subscriptions_verification_info_is_identity_verified_enabled": True,
                "subscriptions_verification_info_verified_since_enabled": True,
                "highlights_tweets_tab_ui_enabled": True,
                "creator_subscriptions_tweet_preview_api_enabled": True,
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
                "responsive_web_graphql_timeline_navigation_enabled": True
            })

            response = await self.graphql_request('UserByScreenName', variables, features)

            user_data = response.get('data', {}).get('user', {})
            if not user_data:
                raise Exception(f"User {username} not found")

            result = user_data.get('result', {})
            if not result:
                raise Exception(f"User {username} not found")

            if result.get('__typename') == 'UserUnavailable':
                raise Exception(f"User {username} is unavailable")

            user_id = result.get('rest_id')
            if not user_id:
                raise Exception(f"Could not get ID for user {username}")

            logger.info(f"Found user ID for {username}: {user_id}")
            return user_id

        except Exception as e:
            logger.error(f"Error getting user ID for {username}: {str(e)}")
            raise

    async def follow_user(self, user: str) -> Dict:
        """Follow a user using Twitter API v2"""
        logger.info(f"Following user {user}")
        try:
            # First get user ID if username is provided
            target_user_id = user if user.isdigit() else await self.get_user_id(user)

            # Get the numeric user ID from access token
            numeric_user_id = None
            if self.access_token and "-" in self.access_token:
                numeric_user_id = self.access_token.split("-")[0]
            
            if not numeric_user_id:
                raise Exception("Could not extract numeric user ID from access token")

            # Add initial delay for natural timing
            await asyncio.sleep(random.uniform(1.0, 3.0))

            json_data = {
                "target_user_id": target_user_id
            }

            response = await self._make_request(
                method="POST",
                url=f"https://api.twitter.com/2/users/{numeric_user_id}/following",
                json_data=json_data
            )

            if response and 'data' in response:
                following = response['data'].get('following', False)
                if following:
                    logger.info(f"Successfully followed user {target_user_id}")
                    return {
                        "success": True,
                        "target_user_id": target_user_id,
                        "action": "follow",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }

            if 'errors' in response:
                error = response['errors'][0]
                error_msg = error.get('message', 'Unknown error')
                error_code = error.get('code')
                
                if error_code == 88:  # Rate limit
                    logger.error(f"Rate limit reached: {error_msg}")
                    return {
                        "success": False,
                        "error": "Rate limit reached",
                        "rate_limited": True
                    }
                else:
                    logger.error(f"API error: {error_msg}")
                    return {
                        "success": False,
                        "error": error_msg
                    }

            return {
                "success": False,
                "error": "Failed to follow user - unknown error"
            }

        except Exception as e:
            logger.error(f"Error following user {user}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def unfollow_user(self, target_user_id: str) -> Dict:
        """Unfollow a user using Twitter API v2"""
        logger.info(f"Unfollowing user {target_user_id}")
        try:
            # Get the numeric user ID from access token
            numeric_user_id = None
            if self.access_token and "-" in self.access_token:
                numeric_user_id = self.access_token.split("-")[0]
            
            if not numeric_user_id:
                raise Exception("Could not extract numeric user ID from access token")

            # Add initial delay for natural timing
            await asyncio.sleep(random.uniform(1.0, 3.0))

            response = await self._make_request(
                method="DELETE",
                url=f"https://api.twitter.com/2/users/{numeric_user_id}/following/{target_user_id}"
            )

            if response and 'data' in response:
                following = not response['data'].get('following', True)
                if following:
                    logger.info(f"Successfully unfollowed user {target_user_id}")
                    return {
                        "success": True,
                        "target_user_id": target_user_id,
                        "action": "unfollow",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }

            if 'errors' in response:
                error = response['errors'][0]
                error_msg = error.get('message', 'Unknown error')
                error_code = error.get('code')
                
                if error_code == 88:  # Rate limit
                    logger.error(f"Rate limit reached: {error_msg}")
                    return {
                        "success": False,
                        "error": "Rate limit reached",
                        "rate_limited": True
                    }
                else:
                    logger.error(f"API error: {error_msg}")
                    return {
                        "success": False,
                        "error": error_msg
                    }

            return {
                "success": False,
                "error": "Failed to unfollow user"
            }

        except Exception as e:
            logger.error(f"Error unfollowing user {target_user_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def update_profile(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        url: Optional[str] = None,
        location: Optional[str] = None,
        profile_image: Optional[str] = None,
        profile_banner: Optional[str] = None,
        lang: Optional[str] = None
    ) -> Dict:
        """Update user profile settings"""
        logger.info("Updating profile settings")
        try:
            responses = {}
            
            # 1. Update basic profile information if any provided
            if any(x is not None for x in [name, description, url, location]):
                profile_data = {}
                if name is not None:
                    profile_data['name'] = name
                if description is not None:
                    profile_data['description'] = description
                if url is not None:
                    profile_data['url'] = url
                if location is not None:
                    profile_data['location'] = location

                profile_response = await self._make_request(
                    method="POST",
                    url=API_ENDPOINTS['profile_update'],
                    data=profile_data
                )
                responses['profile_update'] = profile_response

            # 2. Update language settings if provided
            if lang is not None:
                lang_data = {'lang': lang}
                settings_response = await self._make_request(
                    method="POST",
                    url=API_ENDPOINTS['settings'],
                    data=lang_data
                )
                responses['settings_update'] = settings_response

            # 3. Handle profile image update if provided
            if profile_image:
                from .media_client import MediaClient
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
                
                media_ids = await media_client.upload_media([profile_image])
                if media_ids:
                    profile_image_response = await self._make_request(
                        method="POST",
                        url=API_ENDPOINTS['profile_image'],
                        data={'media_id': media_ids[0]}
                    )
                    responses['profile_image_update'] = profile_image_response

            # 4. Handle profile banner update if provided
            if profile_banner:
                from .media_client import MediaClient
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
                
                media_ids = await media_client.upload_media([profile_banner])
                if media_ids:
                    banner_response = await self._make_request(
                        method="POST",
                        url=API_ENDPOINTS['profile_banner'],
                        data={
                            'media_id': media_ids[0],
                            'width': '1500',
                            'height': '500',
                            'offset_left': '0',
                            'offset_top': '0'
                        }
                    )
                    responses['banner_update'] = banner_response

            # Check if any updates were performed
            if not responses:
                return {
                    "success": False,
                    "error": "No update parameters provided"
                }

            # Check for any errors in responses
            for key, response in responses.items():
                if response and 'errors' in response:
                    error = response['errors'][0]
                    error_msg = error.get('message', 'Unknown error')
                    error_code = error.get('code')
                    
                    if error_code == 88:  # Rate limit
                        logger.error(f"Rate limit reached in {key}")
                        return {
                            "success": False,
                            "error": "Rate limit reached",
                            "rate_limited": True,
                            "retry_after": 900  # 15 minutes
                        }
                    else:
                        logger.error(f"Error in {key}: {error_msg}")
                        return {
                            "success": False,
                            "error": f"Error in {key}: {error_msg}"
                        }

            return {
                "success": True,
                "responses": responses,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error updating profile: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
