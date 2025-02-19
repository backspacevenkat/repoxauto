import logging
import os
import httpx
from typing import Dict, Optional, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class UserOperations:
    def __init__(self, http_client):
        """Initialize UserOperations with HTTP client"""
        self.http_client = http_client

    async def get_user_id(self, username: str) -> str:
        """Get user ID from username"""
        logger.info(f"Getting user ID for {username}")
        variables = {
            "screen_name": username,
            "withSafetyModeUserFields": True
        }

        try:
            response = await self.http_client.graphql_request('UserByScreenName', variables)

            # Check if user data exists and has a result 
            user_data = response.get('data', {}).get('user', {})
            if not user_data:
                logger.error(f"No user data found for {username}")
                raise Exception(f"User {username} not found")

            # Get the result object which contains user details
            result = user_data.get('result', {})
            if not result:
                logger.error(f"No result data found for {username}")
                raise Exception(f"User {username} not found")

            # Check if user is unavailable
            if result.get('__typename') == 'UserUnavailable':
                logger.error(f"User {username} is unavailable")
                raise Exception(f"User {username} is unavailable")

            # Get the rest_id (user ID)
            user_id = result.get('rest_id')
            if not user_id:
                logger.error(f"No user ID found for {username}")
                raise Exception(f"Could not get ID for user {username}")

            logger.info(f"Found user ID for {username}: {user_id}")
            return user_id

        except Exception as e:
            logger.error(f"Error getting user ID for {username}: {str(e)}")
            raise

    async def follow_user(self, user: str) -> Dict:
        """Follow a user by username or ID"""
        logger.info(f"Following user {user}")
        try:
            # Get user ID if username provided
            if not user.isdigit():
                user = await self.get_user_id(user)

            variables = {
                "userId": user,
                "includePromotedContent": False
            }

            response = await self.http_client.graphql_request('FollowUser', variables)

            if response and response.get('data', {}).get('follow_user'):
                return {
                    "success": True,
                    "user_id": user,
                    "action": "follow",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

            return {
                "success": False,
                "error": "Failed to follow user"
            }

        except Exception as e:
            logger.error(f"Error following user {user}: {str(e)}")
            raise

    async def unfollow_user(self, user: str) -> Dict:
        """Unfollow a user by username or ID"""
        logger.info(f"Unfollowing user {user}")
        try:
            # Get user ID if username provided
            if not user.isdigit():
                user = await self.get_user_id(user)

            variables = {
                "userId": user,
                "includePromotedContent": False
            }

            response = await self.http_client.graphql_request('UnfollowUser', variables)

            if response and response.get('data', {}).get('unfollow_user'):
                return {
                    "success": True,
                    "user_id": user,
                    "action": "unfollow",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

            return {
                "success": False,
                "error": "Failed to unfollow user"
            }

        except Exception as e:
            logger.error(f"Error unfollowing user {user}: {str(e)}")
            raise

    async def update_profile(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        url: Optional[str] = None,
        location: Optional[str] = None,
        profile_image: Optional[str] = None,
        profile_banner: Optional[str] = None,
        lang: Optional[str] = None,
        new_login: Optional[str] = None
    ) -> Dict:
        """Update user profile information"""
        logger.info("Updating profile settings")
        try:
            responses = {}
            update_data = {}

            # Collect profile update data
            if name is not None:
                update_data['name'] = name
            if description is not None:
                update_data['description'] = description
            if url is not None:
                update_data['url'] = url
            if location is not None:
                update_data['location'] = location
            if lang is not None:
                update_data['lang'] = lang

            # Update basic profile information if any provided
            if update_data:
                profile_response = await self.http_client.make_request(
                    method="POST",
                    url="https://api.twitter.com/1.1/account/update_profile.json",
                    data=update_data
                )
                responses['profile_update'] = profile_response

            # Handle profile image update
            if profile_image:
                image_data = await self._get_media_data(profile_image)
                if image_data:
                    files = {
                        'image': ('image.jpg', image_data, 'image/jpeg')
                    }
                    
                    profile_image_response = await self.http_client.make_request(
                        method="POST",
                        url="https://api.twitter.com/1.1/account/update_profile_image.json",
                        files=files
                    )
                    responses['profile_image_update'] = profile_image_response

            # Handle profile banner update
            if profile_banner:
                banner_data = await self._get_media_data(profile_banner)
                if banner_data:
                    files = {
                        'banner': ('banner.jpg', banner_data, 'image/jpeg')
                    }
                    
                    form_data = {
                        'width': '1500',
                        'height': '500',
                        'offset_left': '0',
                        'offset_top': '0'
                    }
                    
                    banner_response = await self.http_client.make_request(
                        method="POST",
                        url="https://api.twitter.com/1.1/account/update_profile_banner.json",
                        files=files,
                        data=form_data
                    )
                    responses['banner_update'] = banner_response

            # Check for any errors in responses
            for key, response in responses.items():
                if response and 'errors' in response:
                    error_msg = response['errors'][0].get('message', 'Unknown error')
                    error_code = response['errors'][0].get('code')
                    
                    if error_code == 88:  # Rate limit
                        return {
                            "success": False,
                            "error": "Rate limit reached",
                            "rate_limited": True
                        }
                    else:
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
            raise

    async def _get_media_data(self, media_path: str) -> Optional[bytes]:
        """Get media data from URL or file path"""
        try:
            if media_path.startswith(('http://', 'https://')):
                async with httpx.AsyncClient() as client:
                    response = await client.get(media_path)
                    if response.status_code == 200:
                        return response.content
            else:
                possible_paths = [
                    media_path,
                    os.path.join('backend', media_path),
                    os.path.join(os.getcwd(), media_path)
                ]
                
                for path in possible_paths:
                    if os.path.exists(path):
                        with open(path, 'rb') as f:
                            return f.read()

            logger.error(f"Could not get media data from {media_path}")
            return None

        except Exception as e:
            logger.error(f"Error getting media data: {str(e)}")
            return None

    async def get_user_info(self, username: str) -> Dict:
        """Get detailed user information"""
        logger.info(f"Getting user info for {username}")
        try:
            variables = {
                "screen_name": username,
                "withSafetyModeUserFields": True
            }

            response = await self.http_client.graphql_request('UserByScreenName', variables)

            user_data = response.get('data', {}).get('user', {}).get('result', {})
            if not user_data:
                raise Exception(f"User {username} not found")

            legacy = user_data.get('legacy', {})
            professional = user_data.get('professional', {})
            verified_type = user_data.get('verified_type')

            return {
                'id': user_data.get('rest_id'),
                'screen_name': legacy.get('screen_name'),
                'name': legacy.get('name'),
                'description': legacy.get('description'),
                'location': legacy.get('location'),
                'url': legacy.get('url'),
                'profile_image_url': legacy.get('profile_image_url_https'),
                'profile_banner_url': legacy.get('profile_banner_url'),
                'metrics': {
                    'followers_count': legacy.get('followers_count'),
                    'following_count': legacy.get('friends_count'),
                    'tweets_count': legacy.get('statuses_count'),
                    'likes_count': legacy.get('favourites_count'),
                    'media_count': legacy.get('media_count')
                },
                'verified': legacy.get('verified'),
                'protected': legacy.get('protected'),
                'created_at': legacy.get('created_at'),
                'professional': professional,
                'verified_type': verified_type
            }

        except Exception as e:
            logger.error(f"Error getting user info for {username}: {str(e)}")
            raise

    async def block_user(self, user: str) -> Dict:
        """Block a user by username or ID"""
        logger.info(f"Blocking user {user}")
        try:
            # Get user ID if username provided
            if not user.isdigit():
                user = await self.get_user_id(user)

            variables = {
                "userId": user
            }

            response = await self.http_client.graphql_request('BlockUser', variables)

            if response and response.get('data', {}).get('block_user'):
                return {
                    "success": True,
                    "user_id": user,
                    "action": "block",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

            return {
                "success": False,
                "error": "Failed to block user"
            }

        except Exception as e:
            logger.error(f"Error blocking user {user}: {str(e)}")
            raise

    async def unblock_user(self, user: str) -> Dict:
        """Unblock a user by username or ID"""
        logger.info(f"Unblocking user {user}")
        try:
            # Get user ID if username provided
            if not user.isdigit():
                user = await self.get_user_id(user)

            variables = {
                "userId": user
            }

            response = await self.http_client.graphql_request('UnblockUser', variables)

            if response and response.get('data', {}).get('unblock_user'):
                return {
                    "success": True,
                    "user_id": user,
                    "action": "unblock",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

            return {
                "success": False,
                "error": "Failed to unblock user"
            }

        except Exception as e:
            logger.error(f"Error unblocking user {user}: {str(e)}")
            raise