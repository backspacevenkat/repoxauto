import logging
import httpx
import json
import time
import asyncio
import ssl
import random
import uuid
import string
import os
import mimetypes
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urljoin, urlparse

logger = logging.getLogger(__name__)

class TwitterClient:
    def __init__(
        self,
        account_no: str,
        auth_token: str,
        ct0: str,
        proxy_config: Optional[Dict[str, str]] = None,
        user_agent: Optional[str] = None
    ):
        # GraphQL endpoint IDs
        self.GRAPHQL_ENDPOINTS = {
            # User endpoints
            'UserByScreenName': 'QGIw94L0abhuohrr76cSbw',
            'UserByRestId': 'LWxkCeL8Hlx0-f24DmPAJw',
            'UserTweets': 'TK4W-Bktk8AJk0L1QZnkrg',
            'UserTweetsAndReplies': 'fdVJJtT2C-3fP_jlHuvhJw',
            'UserMedia': '2EDA1hY0Ma1VYhfISprU3w',
            'UserHighlightsTweets': 'dJPR7N024yrPJK6TOUBxwQ',
            'UserArticlesTweets': 'pcisu746wTEXNSTyvot20g',
            'UserPromotableTweets': 'esHMCbeIH6QboX73Cc6s_A',
            'UserSuperFollowTweets': 'GG0aR-UxgSTXme0k7Bbw2w',
            'UserBusinessProfileTeamTimeline': 'vinCKl_qrmPIdi4iPoFUZw',

            # Tweet actions
            'CreateTweet': 'BjT3MvG1CwfTuJxTLX4ovg',
            'DeleteTweet': 'VaenaVgh5q5ih7kvyVjgtg',
            'FavoriteTweet': 'lI07N6Otwv1PhnEgXILM7A',
            'UnfavoriteTweet': 'ZYKSe-w7KEslx3JhSIk5LA',
            'CreateRetweet': 'ojPdsZsimiJrUGLR1sjUtA',
            'DeleteRetweet': 'iQtK4dl5hBmXewYZuEOKVw',
            'CreateBookmark': 'aoDbu3RHznuiSkQ9aNM67Q',
            'DeleteBookmark': 'Wlmlj2-xzyS1GN3a6cj-mQ',
            'CreateHighlight': '7jEc7ECTTDcNaqsMhjTxXg',
            'DeleteHighlight': 'ea-VVDSLIEYNY2_2aPg3Uw',
            'PinTweet': 'VIHsNu89pK-kW35JpHq7Xw',
            'UnpinTweet': 'BhKei844ypCyLYCg0nwigw',
            'ModerateTweet': 'pjFnHGVqCjTcZol0xcBJjw',
            'UnmoderateTweet': 'pVSyu6PA57TLvIE4nN2tsA',

            # Tweet queries
            'TweetDetail': 'iP4-On5YPLPgO9mjKRb2Gg',
            'TweetResultByRestId': 'YJH3-GevIceLRs0zZ2-QPA',
            'TweetResultsByRestIds': 'C5L2RCyOj4wC0QTZ91AoAg',
            'TweetEditHistory': 'iBsxttUh2-hZ61IuLXMubQ',
            'TweetRelatedVideos': '4YQgtC48cKTdX4Rb4bplpw',

            # Timeline queries
            'HomeTimeline': 'Iaj4kAIobIAtigNaYNIOAw',
            'HomeLatestTimeline': '4U9qlz3wQO8Pw1bRGbeR6A',
            'SearchTimeline': 'oyfSj18lHmR7VGC8aM2wpA',
            'ListLatestTweetsTimeline': 'rTndDGyFlXAmeXR4RfFe1A',
            'ListRankedTweetsTimeline': '5ZVLTQkOIWBsDqTQhZjpUA',
            'BookmarkTimeline': 'Ds7FCVYEIivOKHsGcE84xQ',
            'BookmarkFolderTimeline': 'FXE0-Pll4gb7yFh1TpnofQ',

            # Social connections
            'Followers': 'hfD3Y9FI9sF-HuOkAWFDoA',
            'Following': 'gsxNGYhRKA6iYYSInE9qew',
            'Likes': 'oLLzvV4gwmdq_nhPM4cLwg',
            'FollowersYouKnow': 'qJeoLDaL_PO82fjiaK2EYA',
            'BlueVerifiedFollowers': 'cLhhFfu1w4AOBLhzNGrvog',
            'SuperFollowers': '2rytnfKQnO6Bb7cX6CBKrQ',
            'Favoriters': 'vBja3iGK9PKvuLcuB_FWxw',
            'Retweeters': '4WvZLoEOpDHJg1wsw39KZg',

            # Lists
            'ListBySlug': 'mBGC0yBw82sMmeE9FbByQg',
            'ListByRestId': 'smn3p8ZgN724FbaK4roVtQ',
            'ListMembers': 'iVWwnCUe6LrHv3C8Q-36Yg',
            'ListMemberships': 'Xheu6POxwgqKuUgIqrGC8g',
            'ListSubscribers': '1FBDPYNBvBXSgoAc9MvOXg',
            'ListOwnerships': 'hcdkJzrMu07yf5oeo-mCDQ',

            # Communities
            'CommunityByRestId': 'o5M-3G_1fTbscKNqE3NOLg',
            'CommunityTweetsTimeline': 'oCl6Yhd5WAPXouBytkaXRw',
            'CommunityMediaTimeline': 'qqJhXaayVPymEmVVh3ljWQ',
            'CommunitiesRankedTimeline': 'VeqCHFQ3ITJkTInrnwajsg',

            # Explore and trends
            'ExplorePage': 'GDqOD11KMZrrORIIe4q5Lw',
            'ExploreSidebar': 'ZQPE2AJgdo3ydgxNW2I7Fg',
            'TrendHistory': 'r2hMlbYH8j1LfzDM3A-c7A',

            # Settings and preferences
            'UserPreferences': 'xFxU-O8hEYe74ovNVU74jA',
            'ViewerEmailSettings': 'JpjlNgn4sLGvS6tgpTzYBg',
            'DataSaverMode': 'xF6sXnKJfS2AOylzxRjf6A',

            # Authentication
            'AuthenticatePeriscope': 'r7VUmxbfqNkx7uwjgONSNw',
            'DeviceIsVerified': '_384ihv8PithUm1UbGfAyA',
            'GeneratePinCode': '-Ja49b1NyF9nkZtiMQ4iiw'
        }
        
        self.account_no = account_no
        self.auth_token = auth_token
        self.ct0 = ct0
        self.proxy_config = proxy_config
        self.user_agent = user_agent or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.client = None

        # Set up proxy URL with proper encoding and validation
        self.proxy_url = None
        if proxy_config:
            try:
                # Get and validate proxy details from config
                username = proxy_config.get('proxy_username')
                password = proxy_config.get('proxy_password')
                host = proxy_config.get('proxy_url')
                port = proxy_config.get('proxy_port')

                # Validate all required fields are present
                if not all([username, password, host, port]):
                    missing = []
                    if not username: missing.append('proxy_username')
                    if not password: missing.append('proxy_password')
                    if not host: missing.append('proxy_url')
                    if not port: missing.append('proxy_port')
                    logger.error(f"Missing proxy configuration for account {account_no}: {', '.join(missing)}")
                    raise ValueError(f"Missing proxy configuration: {', '.join(missing)}")

                # Log proxy setup details
                logger.info(f"Setting up proxy for {self.account_no}")
                logger.info(f"Host: {host}, Port: {port}")
                logger.info(f"Username length: {len(str(username))}, Password length: {len(str(password))}")
                
                # Properly encode username and password
                encoded_username = quote(str(username), safe='')
                encoded_password = quote(str(password), safe='')
                
                # Build and validate proxy URL
                self.proxy_url = f"http://{encoded_username}:{encoded_password}@{host}:{port}"
                
                # Validate URL format
                if not self.proxy_url.startswith('http://'):
                    raise ValueError("Invalid proxy URL format")
                
                logger.info(f"Proxy URL configured successfully for account {account_no}")
                
            except Exception as e:
                logger.error(f"Failed to configure proxy for account {account_no}: {str(e)}")
                self.proxy_url = None
                raise Exception(f"Proxy configuration failed: {str(e)}")
        else:
            logger.info(f"No proxy configuration provided for account {account_no}")

        # Common headers with proper encoding
        # More realistic browser headers
        self.headers = {
            "User-Agent": self.user_agent,
            "Authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs=1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA",
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-client-language": "en",
            "x-twitter-active-user": "yes",
            "content-type": "application/json",
            "x-csrf-token": ct0,
            "cookie": f"auth_token={auth_token}; ct0={ct0}; lang=en",
            "Referer": "https://twitter.com/home",
            "x-client-transaction-id": f"client-transaction-{int(time.time() * 1000)}",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "accept-encoding": "gzip, deflate, br",
            "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "dnt": "1",
            "pragma": "no-cache",
            "cache-control": "no-cache"
        }

        # Default features for GraphQL requests
        self.DEFAULT_FEATURES = {
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "tweetypie_unmention_optimization_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
            "rweb_lists_timeline_redesign_enabled": True,
            "responsive_web_media_download_video_enabled": True,
            "responsive_web_home_pinned_timelines_enabled": True,
            "responsive_web_twitter_blue_verified_badge_is_enabled": True,
            "vibe_api_enabled": True,
            "interactive_text_enabled": True,
            "responsive_web_text_conversations_enabled": False,
            "highlights_tweets_tab_ui_enabled": True,
            "subscriptions_verification_info_is_identity_verified_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "hidden_profile_likes_enabled": True,
            "hidden_profile_subscriptions_enabled": True,
            "responsive_web_twitter_article_notes_tab_enabled": True,
            "subscriptions_verification_info_enabled": True,
            "super_follow_badge_privacy_enabled": True,
            "super_follow_tweet_api_enabled": True,
            "profile_label_improvements_pcf_label_in_post_enabled": False,
            "rweb_tipjar_consumption_enabled": True,
            "premium_content_api_read_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
            "articles_preview_enabled": True,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "subscriptions_feature_can_gift_premium": False
        }

    async def upload_media(self, media_paths: List[str], media_category: str = "tweet_image") -> List[str]:
        """Upload media to Twitter and return list of media_ids"""
        logger.info(f"Uploading media {media_paths}")
        try:
            # Ensure media_paths is a list
            if isinstance(media_paths, str):
                paths = [media_paths]
            else:
                paths = media_paths
            logger.info(f"Processing media files: {paths}")
            
            media_ids = []
            for path in paths:
                # Detect media type from file extension
                media_type, _ = mimetypes.guess_type(path)
                if not media_type:
                    # Default to jpeg if can't detect
                    extension = os.path.splitext(path)[1].lower()
                    if extension in ['.jpg', '.jpeg']:
                        media_type = 'image/jpeg'
                    elif extension == '.png':
                        media_type = 'image/png'
                    elif extension == '.gif':
                        media_type = 'image/gif'
                    elif extension in ['.mp4', '.m4v']:
                        media_type = 'video/mp4'
                    else:
                        media_type = 'image/jpeg'  # Default fallback
                
                logger.info(f"Detected media type: {media_type} for {path}")

                # Validate file exists and is not empty
                if not os.path.exists(path):
                    logger.error(f"Media file not found: {path}")
                    raise FileNotFoundError(f"Media file not found: {path}")
                
                if os.path.getsize(path) == 0:
                    logger.error(f"Media file is empty: {path}")
                    raise ValueError(f"Media file is empty: {path}")

                # Read media file
                with open(path, 'rb') as f:
                    media_data = f.read()

                # INIT phase
                init_url = "https://upload.twitter.com/1.1/media/upload.json"
                init_data = {
                    "command": "INIT",
                    "total_bytes": len(media_data),
                    "media_type": media_type,
                    "media_category": media_category
                }

                init_response = await self._make_request(
                    "POST",
                    init_url,
                    json_data=init_data
                )

                media_id = init_response.get('media_id_string')
                if not media_id:
                    raise Exception(f"Failed to initialize media upload for {path}")

                # APPEND phase
                chunk_size = 5 * 1024 * 1024  # 5MB chunks
                segment_index = 0

                for i in range(0, len(media_data), chunk_size):
                    chunk = media_data[i:i + chunk_size]
                    append_data = {
                        "command": "APPEND",
                        "media_id": media_id,
                        "segment_index": segment_index,
                        "media": chunk
                    }

                    await self._make_request(
                        "POST",
                        init_url,
                        json_data=append_data
                    )
                    segment_index += 1

                # FINALIZE phase
                finalize_data = {
                    "command": "FINALIZE",
                    "media_id": media_id
                }

                await self._make_request(
                    "POST",
                    init_url,
                    json_data=finalize_data
                )

                media_ids.append(media_id)
                logger.info(f"Successfully uploaded {path} with ID {media_id}")

            return media_ids

        except Exception as e:
            logger.error(f"Error uploading media: {str(e)}")
            raise

    async def reply_tweet(self, tweet_id: str, text_content: str, media: Optional[str] = None, api_method: str = 'graphql') -> Dict:
        """Reply to a tweet using either GraphQL or REST API"""
        logger.info(f"Replying to tweet {tweet_id} using {api_method}")
        try:
            # Process media if provided
            media_ids = []
            if media:
                try:
                    # Handle multiple media files
                    media_paths = [path.strip() for path in media.split(',') if path.strip()]
                    logger.info(f"Processing media files: {media_paths}")
                    
                    # Upload each media file
                    media_ids = []
                    for media_path in media_paths:
                        try:
                            # Ensure media file exists
                            if not os.path.exists(media_path):
                                logger.error(f"Media file not found: {media_path}")
                                continue
                                
                            # Upload media
                            uploaded_ids = await self.upload_media([media_path])
                            if not uploaded_ids:
                                logger.error(f"Failed to upload media file: {media_path}")
                                continue
                                
                            media_ids.extend(uploaded_ids)
                            logger.info(f"Successfully uploaded {media_path} with ID: {uploaded_ids[0]}")
                            
                            # Add small delay between uploads
                            await asyncio.sleep(1)
                            
                        except Exception as e:
                            logger.error(f"Error uploading {media_path}: {str(e)}")
                            continue
                    
                    if not media_ids:
                        raise Exception("No media files were uploaded successfully")
                        
                    logger.info(f"Successfully uploaded all media files with IDs: {media_ids}")
                except Exception as e:
                    logger.error(f"Error processing media: {str(e)}")
                    raise

            if api_method == 'graphql':
                # GraphQL method with correct variables structure
                variables = {
                    "tweet_text": text_content,
                    "reply": {
                        "in_reply_to_tweet_id": str(tweet_id),
                        "exclude_reply_user_ids": []
                    },
                    "media": {
                        "media_ids": media_ids,
                        "tagged_users": []
                    } if media_ids else None,
                    "semantic_annotation_ids": [],
                    "dark_request": False
                }

                try:
                    response = await self.graphql_request('CreateTweet', variables)
                    
                    # Check for errors in response
                    if 'errors' in response:
                        error_msg = response['errors'][0].get('message', 'Unknown error')
                        logger.error(f"Failed to reply to tweet {tweet_id} - {error_msg}")
                        return {
                            "success": False,
                            "error": error_msg
                        }

                    # Extract tweet data with multiple fallback paths
                    tweet_data = None
                    tweet_paths = [
                        lambda: response.get('data', {}).get('create_tweet', {}).get('tweet', {}),
                        lambda: response.get('data', {}).get('tweet_create', {}).get('tweet', {}),
                        lambda: response.get('data', {}).get('tweet', {}),
                        lambda: response.get('tweet', {})
                    ]

                    for get_tweet in tweet_paths:
                        try:
                            data = get_tweet()
                            if data and isinstance(data, dict):
                                tweet_data = data
                                break
                        except Exception:
                            continue

                    if tweet_data:
                        # Get tweet ID with fallbacks
                        tweet_id = str(
                            tweet_data.get('rest_id') or 
                            tweet_data.get('id_str') or 
                            tweet_data.get('id')
                        )
                        
                        if tweet_id:
                            return {
                                "success": True,
                                "tweet_id": tweet_id,
                                "text": tweet_data.get('text') or tweet_data.get('full_text'),
                                "created_at": tweet_data.get('created_at'),
                                "type": "reply_tweet"  # Match TaskType.REPLY value
                            }

                    logger.error(f"Could not extract tweet data from response: {json.dumps(response, indent=2)}")
                    return {
                        "success": False,
                        "error": "Failed to extract tweet data from response"
                    }
                    
                except Exception as e:
                    logger.error(f"Error in GraphQL reply: {str(e)}")
                    return {
                        "success": False,
                        "error": str(e)
                    }
            else:
                # REST API method
                data = {
                    "text": text_content,
                    "reply": {"in_reply_to_tweet_id": str(tweet_id)},
                    "media": {"media_ids": [str(id) for id in media_ids]} if media_ids else {}
                }

                response = await self._make_request(
                    "POST",
                    "https://api.twitter.com/2/tweets",
                    json_data=data,
                    headers={"Content-Type": "application/json"}
                )

                if response.get('data'):
                    return {
                        "type": "reply_tweet",  # Match TaskType.REPLY value
                        "success": True,
                        "tweet_id": response['data'].get('id'),
                        "text": response['data'].get('text')
                    }

            raise Exception("Failed to reply to tweet")

        except Exception as e:
            logger.error(f"Error replying to tweet {tweet_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def quote_tweet(self, tweet_id: str, text_content: str, media: Optional[str] = None, api_method: str = 'graphql') -> Dict:
        """Quote tweet using either GraphQL or REST API"""
        logger.info(f"Quote tweeting {tweet_id} using {api_method}")
        try:
            # Process media if provided
            media_ids = []
            if media:
                try:
                    # Handle multiple media files
                    media_paths = [path.strip() for path in media.split(',') if path.strip()]
                    logger.info(f"Processing media files: {media_paths}")
                    
                    # Upload each media file
                    media_ids = []
                    for media_path in media_paths:
                        try:
                            # Ensure media file exists
                            if not os.path.exists(media_path):
                                logger.error(f"Media file not found: {media_path}")
                                continue
                                
                            # Upload media
                            uploaded_ids = await self.upload_media([media_path])
                            if not uploaded_ids:
                                logger.error(f"Failed to upload media file: {media_path}")
                                continue
                                
                            media_ids.extend(uploaded_ids)
                            logger.info(f"Successfully uploaded {media_path} with ID: {uploaded_ids[0]}")
                            
                            # Add small delay between uploads
                            await asyncio.sleep(1)
                            
                        except Exception as e:
                            logger.error(f"Error uploading {media_path}: {str(e)}")
                            continue
                    
                    if not media_ids:
                        raise Exception("No media files were uploaded successfully")
                        
                    logger.info(f"Successfully uploaded all media files with IDs: {media_ids}")
                except Exception as e:
                    logger.error(f"Error processing media: {str(e)}")
                    raise

            if api_method == 'graphql':
                # GraphQL method with correct variables structure
                variables = {
                    "tweet_text": text_content,
                    "attachment_url": f"https://twitter.com/i/status/{tweet_id}",
                    "media": {
                        "media_ids": media_ids,
                        "tagged_users": []
                    } if media_ids else None,
                    "semantic_annotation_ids": [],
                    "dark_request": False
                }

                try:
                    response = await self.graphql_request('CreateTweet', variables)
                    
                    # Check for errors in response
                    if 'errors' in response:
                        error_msg = response['errors'][0].get('message', 'Unknown error')
                        logger.error(f"Failed to quote tweet {tweet_id} - {error_msg}")
                        return {
                            "success": False,
                            "error": error_msg
                        }

                    # Extract tweet data with multiple fallback paths
                    tweet_data = None
                    tweet_paths = [
                        lambda: response.get('data', {}).get('create_tweet', {}).get('tweet', {}),
                        lambda: response.get('data', {}).get('tweet_create', {}).get('tweet', {}),
                        lambda: response.get('data', {}).get('tweet', {}),
                        lambda: response.get('tweet', {})
                    ]

                    for get_tweet in tweet_paths:
                        try:
                            data = get_tweet()
                            if data and isinstance(data, dict):
                                tweet_data = data
                                break
                        except Exception:
                            continue

                    if tweet_data:
                        # Get tweet ID with fallbacks
                        tweet_id = str(
                            tweet_data.get('rest_id') or 
                            tweet_data.get('id_str') or 
                            tweet_data.get('id')
                        )
                        
                        if tweet_id:
                            return {
                                "success": True,
                                "tweet_id": tweet_id,
                                "text": tweet_data.get('text') or tweet_data.get('full_text'),
                                "created_at": tweet_data.get('created_at'),
                                "type": "quote_tweet"  # Match TaskType.QUOTE value
                            }

                    logger.error(f"Could not extract tweet data from response: {json.dumps(response, indent=2)}")
                    return {
                        "success": False,
                        "error": "Failed to extract tweet data from response"
                    }
                    
                except Exception as e:
                    logger.error(f"Error in GraphQL quote: {str(e)}")
                    return {
                        "success": False,
                        "error": str(e)
                    }
            else:
                # REST API method
                data = {
                    "text": text_content,
                    "quote_tweet_id": str(tweet_id),
                    "media": {"media_ids": [str(id) for id in media_ids]} if media_ids else {}
                }

                response = await self._make_request(
                    "POST",
                    "https://api.twitter.com/2/tweets",
                    json_data=data,
                    headers={"Content-Type": "application/json"}
                )

                if response.get('data'):
                    return {
                        "type": "quote_tweet",  # Match TaskType.QUOTE value
                        "success": True,
                        "tweet_id": response['data'].get('id'),
                        "text": response['data'].get('text')
                    }

            raise Exception("Failed to quote tweet")

        except Exception as e:
            logger.error(f"Error quote tweeting {tweet_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _init_client(self):
        """Initialize HTTP client with proxy if configured"""
        try:
            # If client exists and is still active, return
            if self.client and not self.client.is_closed:
                return

            # Close existing client if it exists
            if self.client:
                try:
                    await self.client.aclose()
                except:
                    pass
                self.client = None

            # Basic client configuration with improved timeout and proxy settings
            client_config = {
                "timeout": httpx.Timeout(
                    connect=random.uniform(20.0, 30.0),  # Increased connection timeout
                    read=random.uniform(45.0, 60.0),    # Increased read timeout
                    write=random.uniform(45.0, 60.0),   # Increased write timeout
                    pool=random.uniform(45.0, 60.0)     # Increased pool timeout
                ),
                "follow_redirects": True,
                "verify": False,  # Disable SSL verification for proxies
                "http2": False,  # Disable HTTP/2 to avoid SSL issues
                "trust_env": False,  # Don't use system proxy settings
                "limits": httpx.Limits(
                    max_keepalive_connections=random.randint(3, 7),  # Randomized connections
                    max_connections=random.randint(8, 12),           # Randomized max connections
                    keepalive_expiry=random.uniform(25.0, 35.0)     # Randomized expiry
                ),
                "transport": httpx.AsyncHTTPTransport(retries=5)  # Increased retries
            }

            # Add proxy configuration if available
            if self.proxy_url:
                try:
                    # Test proxy URL format
                    parsed = urlparse(self.proxy_url)
                    if not all([parsed.scheme, parsed.hostname, parsed.port, parsed.username, parsed.password]):
                        raise ValueError("Invalid proxy URL format")
                    
                    # Configure transport with proxy
                    transport = httpx.AsyncHTTPTransport(
                        proxy=httpx.URL(self.proxy_url),
                        verify=False,
                        retries=2
                    )
                    client_config["transport"] = transport
                    
                    logger.info(f"Proxy configuration added to client for account {self.account_no}")
                    
                    # Log full configuration for debugging
                    debug_config = {**client_config}
                    if "transport" in debug_config:
                        proxy_url = self.proxy_url
                        # Mask credentials in log
                        parsed = urlparse(proxy_url)
                        masked_url = f"{parsed.scheme}://*****:****@{parsed.hostname}:{parsed.port}"
                        debug_config["transport"] = f"<httpx.AsyncHTTPTransport object with proxy={masked_url}>"
                    logger.info(f"Client configuration: {debug_config}")
                except Exception as e:
                    logger.error(f"Failed to configure proxy in client: {str(e)}")
                    raise Exception(f"Failed to configure proxy in client: {str(e)}")

            # Initialize client directly without test request
            self.client = httpx.AsyncClient(**client_config)
            logger.info(f"Successfully initialized client for account {self.account_no}")
            
        except Exception as e:
            logger.error(f"Failed to initialize client: {str(e)}")
            if self.client:
                try:
                    await self.client.aclose()
                except:
                    pass
                self.client = None
            raise Exception(f"Failed to initialize HTTP client: {str(e)}")

    async def _make_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> Dict:
        """Make HTTP request with retries and error handling"""
        # Add random delay between requests (1 to 3 seconds)
        await asyncio.sleep(random.uniform(1, 3))
        
        # Add random jitter to avoid patterns
        if random.random() < 0.3:  # 30% chance of additional delay
            await asyncio.sleep(random.uniform(0.1, 0.5))

        retries = 3
        last_error = None
        
        while retries > 0:
            try:
                # Initialize client if needed
                if not self.client or self.client.is_closed:
                    await self._init_client()
                
                if not self.client:
                    raise Exception("Failed to initialize HTTP client")

                # Ensure params are properly encoded
                if params:
                    params = {k: v.encode('utf-8').decode('utf-8') if isinstance(v, str) else v 
                             for k, v in params.items()}

                # Update dynamic headers with more randomization
                self.headers.update({
                    "x-client-transaction-id": f"client-transaction-{int(time.time() * 1000)}",
                    "x-client-uuid": str(uuid.uuid4()),
                    "accept-language": random.choice([
                        "en-US,en;q=0.9",
                        "en-GB,en;q=0.9",
                        "en-CA,en;q=0.9"
                    ])
                })
                
                response = await self.client.request(
                    method,
                    url,
                    params=params,
                    json=json_data,
                    headers=self.headers,
                    follow_redirects=True
                )
                
                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get("retry-after", "60"))
                    logger.warning(f"Rate limited. Waiting {retry_after} seconds...")
                    await asyncio.sleep(retry_after)
                    retries -= 1
                    continue

                # Handle proxy authentication errors
                if response.status_code == 407:
                    logger.error(f"Proxy authentication failed for account {self.account_no}")
                    raise Exception("Proxy authentication failed")

                # Handle authentication errors
                if response.status_code in (401, 403):
                    logger.error(f"Authentication failed for account {self.account_no}")
                    raise Exception("Authentication failed - check auth_token and ct0")

                # Handle bad requests
                if response.status_code == 400:
                    logger.error(f"Bad request error for account {self.account_no}")
                    raise Exception("Bad request - check request parameters")

                response.raise_for_status()
                
                # Handle response encoding
                try:
                    return response.json()
                except UnicodeDecodeError:
                    # Try decoding with different encodings
                    content = response.content
                    for encoding in ['utf-8', 'latin1', 'ascii']:
                        try:
                            decoded = content.decode(encoding)
                            return json.loads(decoded)
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            continue
                    raise Exception("Failed to decode response content")

            except httpx.ProxyError as e:
                last_error = e
                logger.error(f"Proxy error for account {self.account_no}: {str(e)}")
                if retries > 1:
                    await self.close()
                    await asyncio.sleep(5)
                    self.client = None  # Ensure client is None before retry
                    retries -= 1
                    continue
                raise Exception(f"Proxy error: {str(e)}")

            except httpx.ConnectTimeout as e:
                last_error = e
                logger.error(f"Connection timeout for account {self.account_no}: {str(e)}")
                if retries > 1:
                    await self.close()
                    await asyncio.sleep(5)
                    self.client = None  # Ensure client is None before retry
                    retries -= 1
                    continue
                raise Exception(f"Connection timeout: {str(e)}")

            except httpx.ReadTimeout as e:
                last_error = e
                logger.error(f"Read timeout for account {self.account_no}: {str(e)}")
                if retries > 1:
                    await asyncio.sleep(5)
                    retries -= 1
                    continue
                raise Exception(f"Read timeout: {str(e)}")

            except httpx.HTTPStatusError as e:
                last_error = e
                logger.error(f"HTTP error for account {self.account_no}: {str(e)}")
                if retries > 1:
                    await asyncio.sleep(5)
                    retries -= 1
                    continue
                raise Exception(f"HTTP error: {str(e)}")

            except Exception as e:
                last_error = e
                logger.error(f"Request error for account {self.account_no}: {str(e)}")
                if retries > 1:
                    await asyncio.sleep(5)
                    retries -= 1
                    continue
                raise Exception(f"Request error: {str(last_error or e)}")

    # Add timing patterns to avoid detection
    _last_request_time = 0
    _min_request_interval = 1.0  # Minimum time between requests in seconds
    _jitter_range = (0.5, 2.0)  # Random jitter range in seconds

    async def _add_request_delay(self):
        """Add random delay between requests to avoid detection"""
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        
        if time_since_last < self._min_request_interval:
            # Add random jitter
            jitter = random.uniform(*self._jitter_range)
            delay = self._min_request_interval - time_since_last + jitter
            await asyncio.sleep(delay)
        
        # Update last request time
        self._last_request_time = time.time()

    async def graphql_request(
        self,
        endpoint_name: str,
        variables: Dict,
        features: Optional[Dict] = None
    ) -> Dict:
        """Make a GraphQL request"""
        endpoint_id = self.GRAPHQL_ENDPOINTS.get(endpoint_name)
        if not endpoint_id:
            raise ValueError(f"Unknown GraphQL endpoint: {endpoint_name}")

        # Add delay before request
        await self._add_request_delay()

        logger.info(f"Making GraphQL request to {endpoint_name} for account {self.account_no}")
        
        try:
            base_url = "https://twitter.com/i/api/graphql"
            
            # Use GET for queries, POST for mutations
            if endpoint_name in ['FavoriteTweet', 'CreateRetweet', 'CreateTweet']:
                # For mutations, send a POST request with variables and features
                json_data = {
                    "variables": variables,
                    "features": features or self.DEFAULT_FEATURES,
                    "queryId": endpoint_id
                }
                
                # Log the request details
                logger.info(f"Making GraphQL mutation request to {endpoint_name}")
                logger.info(f"Request data: {json.dumps(json_data, indent=2)}")
                
                response = await self._make_request(
                    "POST",
                    f"{base_url}/{endpoint_id}/{endpoint_name}",
                    json_data=json_data
                )
                
                # Log the response for debugging
                logger.info(f"GraphQL mutation response: {json.dumps(response, indent=2)}")
                
                # Check for specific mutation errors
                if 'errors' in response:
                    error_msg = response['errors'][0].get('message', 'Unknown error')
                    error_type = response['errors'][0].get('type', 'Unknown')
                    logger.error(f"GraphQL mutation error: {error_type} - {error_msg}")
                    raise Exception(f"GraphQL mutation error: {error_type} - {error_msg}")
                
                # Check for missing data
                if 'data' not in response:
                    logger.error(f"No data returned from mutation {endpoint_name}")
                    raise Exception(f"No data returned from mutation {endpoint_name}")
                
                # For CreateTweet mutations, check for specific response structure
                if endpoint_name == 'CreateTweet':
                    tweet_data = response.get('data', {}).get('create_tweet', {})
                    if not tweet_data:
                        logger.error("Missing create_tweet data in response")
                        raise Exception("Missing create_tweet data in response")
                
                # For FavoriteTweet mutations, check for specific response structure
                elif endpoint_name == 'FavoriteTweet':
                    favorite_data = response.get('data', {}).get('favorite_tweet')
                    if not favorite_data:
                        logger.error("Missing favorite_tweet data in response")
                        raise Exception("Missing favorite_tweet data in response")
                
                # For CreateRetweet mutations, check for specific response structure
                elif endpoint_name == 'CreateRetweet':
                    retweet_data = response.get('data', {}).get('create_retweet')
                    if not retweet_data:
                        logger.error("Missing create_retweet data in response")
                        raise Exception("Missing create_retweet data in response")
            else:
                # For queries, use GET with full parameters
                variables_json = json.dumps(variables, ensure_ascii=False)
                features_json = json.dumps(features or self.DEFAULT_FEATURES, ensure_ascii=False)
                
                response = await self._make_request(
                    "GET",
                    f"{base_url}/{endpoint_id}/{endpoint_name}",
                    params={
                        "variables": variables_json,
                        "features": features_json
                    }
                )
            
            # Check for errors in response
            if 'errors' in response:
                error_msg = response['errors'][0].get('message', 'Unknown error')
                logger.error(f"GraphQL error: {error_msg}")
                raise Exception(f"GraphQL error: {error_msg}")
                
            return response
        except Exception as e:
            logger.error(f"GraphQL request failed: {str(e)}")
            raise

    async def get_user_tweets(
        self,
        username: str,
        count: int = 40,
        hours: Optional[int] = None,
        max_replies: Optional[int] = None,
        cursor: Optional[str] = None,
        include_replies: bool = True
    ) -> Dict:
        """Get user tweets using GraphQL"""
        logger.info(f"Getting tweets for user {username}")
        try:
            # First get user ID from username
            user_id = await self.get_user_id(username)
            logger.info(f"Found user ID {user_id} for {username}")

            variables = {
                "userId": user_id,
                "count": count,
                "cursor": cursor,
                "includePromotedContent": False,
                "withQuickPromoteEligibilityTweetFields": True,
                "withVoice": True,
                "withV2Timeline": True,
                "withBirdwatchPivots": False,
                "withVoice": True,
                "withV2Timeline": True,
                "withUserResults": True,
                "withBirdwatchPivots": False,
                "withReplyCount": True,
                "withTweetQuoteCount": True,
                "withTweetResult": True,
                "withHighlightedLabel": True,
                "withArticleRichContentState": False,
                "withInternalReplyCount": True,
                "withReplyContext": True,
                "withTimelinesCount": True,
                "withSuperFollowsTweetFields": True,
                "withSuperFollowsUserFields": True,
                "withUserResults": True,
                "withBirdwatchPivots": False,
                "withReplyCount": True,
                "withVoice": True,
                "withDownvotePerspective": False,
                "withReactionsMetadata": False,
                "withReactionsPerspective": False,
                "withSuperFollowsTweetFields": True,
                "withUserResults": True,
                "withBirdwatchPivots": False,
                "withReplyCount": True,
                "withTweetQuoteCount": True,
                "withTweetResult": True,
                "withTweetResultByRestId": True,
                "withTweetResultByTweetId": True,
                "withTweetBookmarkCount": True,
                "withTweetImpression": True,
                "withTweetView": True,
                "withThreads": True,
                "withConversationControl": True,
                "withArticleRichContentState": False,
                "withBirdwatchPivots": False,
                "withHighlightedLabel": True,
                "withInternalReplyCount": True,
                "withReplyCount": True,
                "withReplyCountV2": True,
                "withTimelinesCount": True,
                "withReplyContext": True,
                "withContextualizedReplyCreation": True,
                "withSelfThreads": True,
                "withExpandedReplyCount": True,
                "withParentTweet": True,
                "withConversationThreads": True,
                "withGlobalObjects": True,
                "withExpandedCard": True,
                "withReplyThreads": True,
                "withThreadedConversation": True,
                "withThreadedConversationV2": True,
                "withThreadedMode": True,
                "withThreadedModeV2": True,
                "withThreadedExpansion": True,
                "withThreadedExpansionV2": True,
                "withThreadedReplies": True,
                "withThreadedRepliesV2": True,
                "withThreadedTweets": True,
                "withThreadedTweetsV2": True,
                "withThreadedConversationWithInjectionsV2": True,
                "withReplies": True,
                "withRuxInjections": False,
                "withClientEventToken": False,
                "withBirdwatchPivots": False,
                "withAuxiliaryUserLabels": False,
                "referrer": "profile",
                "withQuotedTweetResultByRestId": True,
                "withBirdwatchNotes": True
            }

            endpoint = 'UserTweetsAndReplies' if include_replies else 'UserTweets'
            response = await self.graphql_request(endpoint, variables)

            if not response or 'data' not in response:
                logger.error(f"No data found in user tweets response for {user_id}")
                raise Exception("Failed to get user tweets")

            # Extract tweets from response
            tweets = []
            next_cursor = None

            # Try multiple paths to find timeline data
            timeline_data = None
            timeline_paths = [
                lambda: response.get('data', {}).get('user', {}).get('result', {}).get('timeline_v2', {}).get('timeline', {}),
                lambda: response.get('data', {}).get('user', {}).get('result', {}).get('timeline', {}),
                lambda: response.get('data', {}).get('user', {}).get('result', {}).get('tweets_timeline', {}).get('timeline', {}),
                lambda: response.get('data', {}).get('threaded_conversation_with_injections_v2', {})
            ]

            for get_timeline in timeline_paths:
                try:
                    data = get_timeline()
                    if data and isinstance(data, dict):
                        timeline_data = data
                        logger.info("Found timeline data")
                        break
                except Exception as e:
                    continue

            if not timeline_data:
                logger.error(f"No timeline data found for user {user_id}")
                logger.error(f"Response structure: {json.dumps(response, indent=2)}")
                raise Exception("Failed to get timeline data")

            instructions = timeline_data.get('instructions', [])
            if not instructions:
                logger.error(f"No instructions found in timeline for user {user_id}")
                raise Exception("No timeline instructions found")

            for instruction in instructions:
                if instruction.get('type') == 'TimelineAddEntries':
                    entries = instruction.get('entries', [])
                    for entry in entries:
                        if 'cursor-bottom-' in entry.get('entryId', ''):
                            next_cursor = entry.get('content', {}).get('value')
                            continue

                        content = entry.get('content', {})
                        if content.get('entryType') == 'TimelineTimelineItem':
                            item_content = content.get('itemContent', {})
                            tweet_results = item_content.get('tweet_results', {}).get('result', {})
                            
                            if tweet_results:
                                processed_tweet = await self._process_tweet_data(tweet_results)
                                if processed_tweet:
                                    tweets.append(processed_tweet)

            # Filter tweets by time if hours specified
            if hours:
                cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
                tweets = [
                    t for t in tweets 
                    if datetime.strptime(t['created_at'], '%a %b %d %H:%M:%S %z %Y') > cutoff_time
                ]

            # Get replies if max_replies specified
            if max_replies:
                for tweet in tweets:
                    replies_data = await self.get_tweet_replies(tweet['id'], max_replies)
                    tweet['replies'] = replies_data.get('replies', [])

            return {
                'tweets': tweets,
                'next_cursor': next_cursor,
                'username': username
            }

        except Exception as e:
            logger.error(f"Error getting tweets for user {user_id}: {str(e)}")
            raise

    async def get_user_id(self, username: str) -> str:
        """Get user ID from username"""
        logger.info(f"Getting user ID for {username}")
        variables = {
            "screen_name": username,
            "withSafetyModeUserFields": True
        }

        try:
            response = await self.graphql_request('UserByScreenName', variables)

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

    async def get_tweet_replies(
        self,
        tweet_id: str,
        max_replies: int,
        cursor: Optional[str] = None
    ) -> Dict:
        """Get replies for a tweet and detect threads"""
        logger.info(f"Getting replies for tweet {tweet_id}")
        try:
            variables = {
                "focalTweetId": tweet_id,
                "cursor": cursor,
                "count": max_replies * 2,
                "includePromotedContent": False,
                "withCommunity": True,
                "withQuickPromoteEligibilityTweetFields": True,
                "withVoice": True,
                "withV2Timeline": True,
                "withBirdwatchPivots": False,
                "withVoice": True,
                "withV2Timeline": True,
                "withUserResults": True,
                "withBirdwatchPivots": False,
                "withReplyCount": True,
                "withTweetQuoteCount": True,
                "withTweetResult": True,
                "withHighlightedLabel": True,
                "withArticleRichContentState": False,
                "withInternalReplyCount": True,
                "withReplyContext": True,
                "withTimelinesCount": True,
                "withSuperFollowsTweetFields": True,
                "withSuperFollowsUserFields": True,
                "withUserResults": True,
                "withBirdwatchPivots": False,
                "withReplyCount": True,
                "withVoice": True,
                "withDownvotePerspective": False,
                "withReactionsMetadata": False,
                "withReactionsPerspective": False,
                "withSuperFollowsTweetFields": True,
                "withUserResults": True,
                "withBirdwatchPivots": False,
                "withReplyCount": True,
                "withTweetQuoteCount": True,
                "withTweetResult": True,
                "withTweetResultByRestId": True,
                "withTweetResultByTweetId": True,
                "withTweetBookmarkCount": True,
                "withTweetImpression": True,
                "withTweetView": True,
                "withThreads": True,
                "withConversationControl": True,
                "withArticleRichContentState": False,
                "withBirdwatchPivots": False,
                "withHighlightedLabel": True,
                "withInternalReplyCount": True,
                "withReplyCount": True,
                "withReplyCountV2": True,
                "withTimelinesCount": True,
                "withReplyContext": True,
                "withContextualizedReplyCreation": True,
                "withSelfThreads": True,
                "withExpandedReplyCount": True,
                "withParentTweet": True,
                "withConversationThreads": True,
                "withGlobalObjects": True,
                "withExpandedCard": True,
                "withReplyThreads": True,
                "withThreadedConversation": True,
                "withThreadedConversationV2": True,
                "withThreadedMode": True,
                "withThreadedModeV2": True,
                "withThreadedExpansion": True,
                "withThreadedExpansionV2": True,
                "withThreadedReplies": True,
                "withThreadedRepliesV2": True,
                "withThreadedTweets": True,
                "withThreadedTweetsV2": True,
                "withThreadedConversationWithInjectionsV2": True,
                "withReplies": True,
                "withRuxInjections": False,
                "withClientEventToken": False,
                "withBirdwatchPivots": False,
                "withAuxiliaryUserLabels": False,
                "referrer": "tweet",
                "withQuotedTweetResultByRestId": True,
                "withBirdwatchNotes": True
            }

            features = {
                **self.DEFAULT_FEATURES,
                "responsive_web_twitter_blue_verified_badge_is_enabled": True,
                "responsive_web_graphql_exclude_directive_enabled": True,
                "verified_phone_label_enabled": False,
                "responsive_web_graphql_timeline_navigation_enabled": True,
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
                "tweetypie_unmention_optimization_enabled": True,
                "responsive_web_edit_tweet_api_enabled": True,
                "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
                "view_counts_everywhere_api_enabled": True,
                "longform_notetweets_consumption_enabled": True,
                "responsive_web_twitter_article_tweet_consumption_enabled": True,
                "tweet_awards_web_tipping_enabled": False,
                "freedom_of_speech_not_reach_fetch_enabled": True,
                "standardized_nudges_misinfo": True,
                "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
                "rweb_video_timestamps_enabled": True,
                "longform_notetweets_rich_text_read_enabled": True,
                "longform_notetweets_inline_media_enabled": True,
                "responsive_web_enhance_cards_enabled": False,
                "responsive_web_media_download_video_enabled": True,
                "responsive_web_twitter_article_tweet_consumption_enabled": True,
                "responsive_web_media_download_video_enabled": True,
                "responsive_web_graphql_timeline_navigation_enabled": True,
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
                "longform_notetweets_consumption_enabled": True,
                "responsive_web_twitter_article_tweet_consumption_enabled": True,
                "responsive_web_media_download_video_enabled": True,
                "responsive_web_graphql_exclude_directive_enabled": True,
                "verified_phone_label_enabled": False,
                "creator_subscriptions_tweet_preview_api_enabled": True,
                "freedom_of_speech_not_reach_fetch_enabled": True,
                "standardized_nudges_misinfo": True,
                "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
                "responsive_web_graphql_timeline_navigation_enabled": True,
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
                "longform_notetweets_consumption_enabled": True,
                "responsive_web_twitter_article_tweet_consumption_enabled": True,
                "responsive_web_media_download_video_enabled": True,
                "responsive_web_graphql_exclude_directive_enabled": True,
                "verified_phone_label_enabled": False,
                "creator_subscriptions_tweet_preview_api_enabled": True,
                "freedom_of_speech_not_reach_fetch_enabled": True,
                "standardized_nudges_misinfo": True,
                "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
                "responsive_web_graphql_timeline_navigation_enabled": True,
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
                "longform_notetweets_consumption_enabled": True,
                "responsive_web_twitter_article_tweet_consumption_enabled": True,
                "responsive_web_media_download_video_enabled": True
            }

            response = await self.graphql_request('TweetDetail', variables)

            if 'errors' in response:
                logger.error(f"Error in tweet detail response: {response['errors']}")
                return {'replies': [], 'next_cursor': None}

            entries = response.get('data', {}).get('threaded_conversation_with_injections_v2', {}).get('instructions', [])
            if not entries:
                logger.warning(f"No entries found in tweet detail response for tweet {tweet_id}")
                return {'replies': [], 'next_cursor': None}

            # Find the TimelineAddEntries instruction
            timeline_entries = None
            for instruction in entries:
                if instruction.get('type') == 'TimelineAddEntries':
                    timeline_entries = instruction.get('entries', [])
                    break

            if not timeline_entries:
                logger.warning(f"No timeline entries found for tweet {tweet_id}")
                return {'replies': [], 'next_cursor': None}

            # Process entries to get all tweets first
            all_tweets = []
            next_cursor = None
            original_tweet = None

            for entry in entries:
                if 'cursor-bottom' in entry.get('entryId', ''):
                    next_cursor = entry.get('content', {}).get('value')
                    continue

                content = entry.get('content', {})
                if content.get('entryType') == 'TimelineTimelineItem':
                    item_content = content.get('itemContent', {})
                    tweet_results = item_content.get('tweet_results', {}).get('result', {})

                    if tweet_results:
                        processed_tweet = await self._process_tweet_data(tweet_results)
                        if processed_tweet:
                            if processed_tweet['id'] == tweet_id:
                                original_tweet = processed_tweet
                            else:
                                all_tweets.append(processed_tweet)

            if not original_tweet:
                logger.warning(f"Original tweet {tweet_id} not found in response")
                return {'replies': [], 'next_cursor': None}

            # Sort tweets by time
            all_tweets.sort(key=lambda x: datetime.strptime(x['created_at'], '%a %b %d %H:%M:%S %z %Y'))

            # Organize replies and threads
            replies = []
            current_thread = []
            original_author = original_tweet['author']

            for tweet in all_tweets:
                # Check if this is a reply to the original tweet or part of a thread
                is_reply_to_original = tweet.get('reply_to_status_id') == tweet_id
                is_thread = tweet['author'] == original_author
                is_consecutive_reply = False

                # Check if this is a consecutive reply in a thread
                if current_thread and is_thread:
                    last_thread_tweet = current_thread[-1]
                    is_consecutive_reply = (
                        tweet.get('reply_to_status_id') == last_thread_tweet['id'] or
                        tweet.get('conversation_id') == tweet_id or
                        (tweet.get('reply_to_screen_name') == original_author and
                        abs(datetime.strptime(tweet['created_at'], '%a %b %d %H:%M:%S %z %Y').timestamp() -
                        datetime.strptime(last_thread_tweet['created_at'], '%a %b %d %H:%M:%S %z %Y').timestamp()) < 300)
                    )

                # Handle thread continuation
                if is_consecutive_reply:
                    current_thread.append(tweet)
                    continue

                # If we have a thread and got a non-consecutive tweet
                if current_thread:
                    replies.append({
                        'type': 'thread',
                        'tweets': current_thread.copy()
                    })
                    current_thread = []

                # Start a new thread or add as reply
                if is_thread and is_reply_to_original:
                    current_thread.append(tweet)
                elif is_reply_to_original:
                    replies.append({
                        'type': 'reply',
                        'tweet': tweet
                    })

                # Break if we've reached max replies
                if len(replies) >= max_replies:
                    break

            # Add any remaining thread
            if current_thread:
                replies.append({
                    'type': 'thread',
                    'tweets': current_thread
                })

            return {
                'replies': replies[:max_replies],
                'next_cursor': next_cursor if len(replies) >= max_replies else None
            }

        except Exception as e:
            logger.error(f"Error getting replies for tweet {tweet_id}: {str(e)}")
            raise

    async def _process_tweet_data(self, tweet_data: Dict) -> Optional[Dict]:
        """Process raw tweet data including retweets and quoted tweets"""
        try:
            if not tweet_data:
                return None

            # Log the full tweet data structure for debugging
            logger.info(f"Processing tweet data structure: {json.dumps(tweet_data, indent=2)}")

            # Handle retweets
            if 'retweeted_status_result' in tweet_data.get('legacy', {}):
                retweet_data = tweet_data['legacy']['retweeted_status_result']['result']
                processed = await self._process_tweet_data(retweet_data)
                if processed:
                    processed['retweeted_by'] = tweet_data.get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {}).get('screen_name')
                    processed['retweeted_at'] = tweet_data.get('legacy', {}).get('created_at')
                    return processed

            # Get legacy data with additional paths
            legacy = None
            legacy_paths = [
                # Direct legacy paths
                lambda: tweet_data.get('legacy', {}),
                lambda: tweet_data.get('tweet', {}).get('legacy', {}),
                lambda: tweet_data.get('result', {}).get('legacy', {}),
                
                # Tweet results paths
                lambda: tweet_data.get('content', {}).get('itemContent', {}).get('tweet_results', {}).get('result', {}).get('legacy', {}),
                lambda: tweet_data.get('tweet_results', {}).get('result', {}).get('legacy', {}),
                lambda: tweet_data.get('itemContent', {}).get('tweet_results', {}).get('result', {}).get('legacy', {}),
                
                # User results paths
                lambda: tweet_data.get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {}),
                lambda: tweet_data.get('user_results', {}).get('result', {}).get('legacy', {}),
                lambda: tweet_data.get('user', {}).get('legacy', {}),
                
                # Timeline paths
                lambda: tweet_data.get('content', {}).get('itemContent', {}).get('tweet', {}).get('legacy', {}),
                lambda: tweet_data.get('item', {}).get('itemContent', {}).get('tweet_results', {}).get('result', {}).get('legacy', {}),
                lambda: tweet_data.get('tweet', {}).get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {}),
                
                # Additional paths for newer API responses
                lambda: tweet_data.get('data', {}).get('tweet', {}).get('legacy', {}),
                lambda: tweet_data.get('data', {}).get('user', {}).get('result', {}).get('legacy', {}),
                lambda: tweet_data.get('timeline', {}).get('instructions', [{}])[0].get('entries', [{}])[0].get('content', {}).get('itemContent', {}).get('tweet_results', {}).get('result', {}).get('legacy', {}),
                
                # V2 Timeline paths
                lambda: tweet_data.get('tweet', {}).get('result', {}).get('tweet', {}).get('legacy', {}),
                lambda: tweet_data.get('result', {}).get('tweet', {}).get('legacy', {}),
                lambda: tweet_data.get('tweet', {}).get('tweet', {}).get('legacy', {}),
                
                # Legacy tweet paths
                lambda: tweet_data.get('tweet', {}).get('legacy_tweet', {}),
                lambda: tweet_data.get('result', {}).get('legacy_tweet', {}),
                lambda: tweet_data.get('legacy_tweet', {}),
                
                # Newer API paths
                lambda: tweet_data.get('tweet_results', {}).get('result', {}).get('tweet', {}).get('legacy', {}),
                lambda: tweet_data.get('tweet_results', {}).get('result', {}).get('tweet', {}).get('tweet', {}).get('legacy', {}),
                lambda: tweet_data.get('tweet_results', {}).get('result', {}).get('tweet_results', {}).get('result', {}).get('legacy', {})
            ]
            
            for get_legacy in legacy_paths:
                try:
                    legacy_data = get_legacy()
                    if legacy_data and isinstance(legacy_data, dict):
                        # Verify we have essential legacy data
                        if any([
                            legacy_data.get('full_text'),
                            legacy_data.get('text'),
                            legacy_data.get('id_str'),
                            legacy_data.get('created_at'),
                            legacy_data.get('screen_name')  # Also check for screen_name
                        ]):
                            legacy = legacy_data
                            logger.info(f"Found valid legacy data with text: {legacy_data.get('full_text') or legacy_data.get('text')}")
                            break
                except Exception as e:
                    logger.debug(f"Failed to get legacy data from path: {str(e)}")
                    continue

            if not legacy:
                logger.error("Could not find valid legacy data in tweet")
                logger.error(f"Tweet data structure: {json.dumps(tweet_data, indent=2)}")
                return None

            # Get author info with additional paths
            author = None
            author_paths = [
                # Direct user paths
                lambda: tweet_data.get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {}).get('screen_name'),
                lambda: tweet_data.get('user', {}).get('screen_name'),
                lambda: legacy.get('user', {}).get('screen_name'),
                
                # User results paths
                lambda: tweet_data.get('user_results', {}).get('result', {}).get('legacy', {}).get('screen_name'),
                lambda: tweet_data.get('result', {}).get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {}).get('screen_name'),
                lambda: tweet_data.get('content', {}).get('itemContent', {}).get('tweet_results', {}).get('result', {}).get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {}).get('screen_name'),
                
                # Legacy paths
                lambda: legacy.get('screen_name'),
                lambda: tweet_data.get('user', {}).get('legacy', {}).get('screen_name'),
                lambda: tweet_data.get('core', {}).get('user', {}).get('legacy', {}).get('screen_name'),
                
                # Additional paths for newer API responses
                lambda: tweet_data.get('data', {}).get('user', {}).get('screen_name'),
                lambda: tweet_data.get('user_data', {}).get('screen_name'),
                lambda: tweet_data.get('user_info', {}).get('screen_name'),
                lambda: tweet_data.get('tweet', {}).get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {}).get('screen_name'),
                lambda: tweet_data.get('content', {}).get('itemContent', {}).get('user', {}).get('screen_name'),
                lambda: tweet_data.get('timeline', {}).get('instructions', [{}])[0].get('entries', [{}])[0].get('content', {}).get('itemContent', {}).get('user_results', {}).get('result', {}).get('legacy', {}).get('screen_name'),
                
                # V2 Timeline paths
                lambda: tweet_data.get('tweet', {}).get('result', {}).get('tweet', {}).get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {}).get('screen_name'),
                lambda: tweet_data.get('result', {}).get('tweet', {}).get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {}).get('screen_name'),
                lambda: tweet_data.get('tweet', {}).get('tweet', {}).get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {}).get('screen_name'),
                
                # Legacy user paths
                lambda: tweet_data.get('tweet', {}).get('legacy_user', {}).get('screen_name'),
                lambda: tweet_data.get('result', {}).get('legacy_user', {}).get('screen_name'),
                lambda: tweet_data.get('legacy_user', {}).get('screen_name'),
                
                # Newer API paths
                lambda: tweet_data.get('tweet_results', {}).get('result', {}).get('tweet', {}).get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {}).get('screen_name'),
                lambda: tweet_data.get('tweet_results', {}).get('result', {}).get('tweet', {}).get('tweet', {}).get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {}).get('screen_name'),
                lambda: tweet_data.get('tweet_results', {}).get('result', {}).get('tweet_results', {}).get('result', {}).get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {}).get('screen_name')
            ]

            for get_author in author_paths:
                try:
                    potential_author = get_author()
                    if potential_author:
                        author = potential_author
                        logger.info(f"Found author: {author}")
                        break
                except Exception as e:
                    continue

            if not author or not legacy:
                logger.error(f"Could not extract required tweet data.")
                logger.error(f"Legacy data present: {bool(legacy)}")
                logger.error(f"Author found: {bool(author)}")
                logger.error(f"Tweet data keys: {list(tweet_data.keys())}")
                logger.error(f"Tweet data structure: {json.dumps(tweet_data, indent=2)}")
                return None

            # Log successful extraction
            logger.info(f"Successfully extracted author: {author} and legacy data for tweet")

            # Get tweet ID and build URL
            tweet_id = str(tweet_data.get('rest_id') or legacy.get('id_str'))
            if not tweet_id:
                logger.error("Could not find tweet ID")
                return None

            tweet_url = f"https://twitter.com/{author}/status/{tweet_id}"

            # Extract tweet text with multiple fallback paths
            text = None
            text_paths = [
                lambda: legacy.get('full_text'),
                lambda: tweet_data.get('text'),
                lambda: legacy.get('text'),
                lambda: tweet_data.get('legacy', {}).get('full_text'),
                lambda: tweet_data.get('tweet', {}).get('text'),
                lambda: tweet_data.get('tweet', {}).get('legacy', {}).get('full_text'),
                lambda: tweet_data.get('content', {}).get('itemContent', {}).get('tweet_results', {}).get('result', {}).get('legacy', {}).get('full_text'),
                lambda: tweet_data.get('note_tweet', {}).get('note_tweet_results', {}).get('result', {}).get('text'),
                lambda: tweet_data.get('quoted_status_result', {}).get('result', {}).get('legacy', {}).get('full_text')
            ]

            for get_text in text_paths:
                try:
                    potential_text = get_text()
                    if potential_text:
                        text = potential_text
                        logger.info(f"Found tweet text: {text[:100]}...")
                        break
                except Exception as e:
                    continue

            if not text:
                logger.error("Could not find tweet text")
                logger.error(f"Tweet data structure: {json.dumps(tweet_data, indent=2)}")
                return None

            processed = {
                'id': tweet_id,
                'tweet_url': tweet_url,
                'created_at': legacy.get('created_at'),
                'text': text,
                'lang': legacy.get('lang'),
                'source': legacy.get('source'),
                'conversation_id': legacy.get('conversation_id_str'),
                'reply_settings': tweet_data.get('reply_settings'),
                'metrics': {
                    'retweet_count': legacy.get('retweet_count', 0),
                    'reply_count': legacy.get('reply_count', 0),
                    'like_count': legacy.get('favorite_count', 0),
                    'quote_count': legacy.get('quote_count', 0),
                    'view_count': int(tweet_data.get('views', {}).get('count', 0)),
                    'bookmark_count': tweet_data.get('bookmark_count', 0)
                },
                'author': author,
                'is_reply': bool(legacy.get('in_reply_to_status_id_str')),
                'reply_to': legacy.get('in_reply_to_screen_name'),
                'reply_to_status_id': legacy.get('in_reply_to_status_id_str')
            }

            # Extract media
            if 'extended_entities' in legacy:
                processed['media'] = await self._process_media(
                    legacy['extended_entities'].get('media', [])
                )

            # Extract URLs
            if 'entities' in legacy:
                processed['urls'] = await self._process_urls(
                    legacy['entities'].get('urls', [])
                )

            # Handle quoted tweets
            if legacy.get('is_quote_status') and 'quoted_status_result' in tweet_data:
                quoted_data = tweet_data['quoted_status_result']['result']
                quoted_tweet = await self._process_tweet_data(quoted_data)
                if quoted_tweet:
                    processed['quoted_tweet'] = quoted_tweet

            return processed

        except Exception as e:
            logger.error(f"Error processing tweet data: {str(e)}")
            return None

    async def _process_media(self, media_items: List[Dict]) -> List[Dict]:
        """Process media items from tweet"""
        processed = []
        for media in media_items:
            item = {
                'type': media['type'],
                'url': media.get('media_url_https'),
                'alt_text': media.get('ext_alt_text')
            }

            if media['type'] in ['video', 'animated_gif']:
                variants = media.get('video_info', {}).get('variants', [])
                if variants:
                    # Get highest quality video URL
                    video_variants = [v for v in variants if v.get('content_type') == 'video/mp4']
                    if video_variants:
                        highest_bitrate = max(video_variants, key=lambda x: x.get('bitrate', 0))
                        item['video_url'] = highest_bitrate['url']
                        item['duration_ms'] = media.get('video_info', {}).get('duration_millis')

            processed.append(item)
        return processed

    async def _process_urls(self, urls: List[Dict]) -> List[Dict]:
        """Process URLs from tweet"""
        processed = []
        for url in urls:
            processed.append({
                'url': url.get('expanded_url'),
                'display_url': url.get('display_url'),
                'title': url.get('title'),
                'description': url.get('description'),
                'unwound_url': url.get('unwound_url')
            })
        return processed

    async def get_trending_topics(self) -> Dict:
        """
        Fetch trending topics worldwide, US national, and major US cities.
        Merge them, remove duplicates, sort by tweet_volume (descending),
        and perform a basic analysis before returning.
        """
        logger.info("Fetching trending topics from official Twitter v1.1 endpoint...")

        # Dictionary of major US cities and their WOEIDs
        US_CITIES = {
            'New York': 2459115, 'Los Angeles': 2442047, 'Chicago': 2379574,
            'Houston': 2424766, 'Phoenix': 2471390, 'Philadelphia': 2471217,
            'San Antonio': 2487796, 'San Diego': 2487889, 'Dallas': 2388929,
            'San Jose': 2488042, 'Austin': 2357536, 'Jacksonville': 2428344,
            'Fort Worth': 2406080, 'Columbus': 2383660, 'San Francisco': 2487956,
            'Charlotte': 2378426, 'Indianapolis': 2427032, 'Seattle': 2490383,
            'Denver': 2391279, 'Washington': 2514815, 'Boston': 2367105,
            'El Paso': 2397816, 'Detroit': 2391585, 'Nashville': 2457170,
            'Portland': 2475687, 'Memphis': 2449323, 'Oklahoma City': 2464592,
            'Las Vegas': 2436704, 'Louisville': 2442327, 'Baltimore': 2358820
        }

        async def _get_trends_for_location(woeid: int, location_name: str = None) -> List[Dict]:
            """Helper function: fetches trends for a given WOEID"""
            logger.info(f"Fetching trends for WOEID={woeid} ({location_name or 'N/A'})")
            try:
                response = await self._make_request(
                    method="GET",
                    url="https://api.twitter.com/1.1/trends/place.json",
                    params={"id": str(woeid)}
                )

                # The v1.1 endpoint returns a list with one item
                if not isinstance(response, list) or len(response) < 1:
                    logger.warning(f"No trending data returned for WOEID={woeid}")
                    return []

                place_data = response[0]
                trends_info = place_data.get("trends", [])
                as_of = place_data.get("as_of")
                created_at = place_data.get("created_at")

                results = []
                for trend in trends_info:
                    name = trend.get("name")
                    if not name:
                        continue
                    volume = trend.get("tweet_volume") or 0
                    results.append({
                        "name": name,
                        "tweet_volume": volume,
                        "query": trend.get("query"),
                        "url": trend.get("url"),
                        "as_of": as_of,
                        "created_at": created_at,
                        "location": location_name
                    })

                logger.info(f"Found {len(results)} trends for WOEID={woeid}")
                return results

            except Exception as e:
                logger.error(f"Error fetching trends for location WOEID={woeid}: {str(e)}")
                return []

        try:
            # We'll store all combined trends in this list
            all_trends = []
            # Keep track of duplicates by lowercased name
            seen_trends = set()

            # 1) Worldwide (WOEID=1)
            worldwide_trends = await _get_trends_for_location(1, "Worldwide")
            for t in worldwide_trends:
                if t["name"].lower() not in seen_trends:
                    all_trends.append(t)
                    seen_trends.add(t["name"].lower())

            # 2) US National (WOEID=23424977)
            us_trends = await _get_trends_for_location(23424977, "United States")
            for t in us_trends:
                if t["name"].lower() not in seen_trends:
                    all_trends.append(t)
                    seen_trends.add(t["name"].lower())

            # 3) Major US Cities
            for city, woeid in US_CITIES.items():
                city_trends = await _get_trends_for_location(woeid, city)
                for t in city_trends:
                    if t["name"].lower() not in seen_trends:
                        all_trends.append(t)
                        seen_trends.add(t["name"].lower())
                # Sleep briefly to reduce rate-limit risk
                await asyncio.sleep(0.3)

            # Sort all combined trends by tweet_volume descending
            all_trends.sort(key=lambda x: x.get("tweet_volume", 0) or 0, reverse=True)

            # Optionally analyze them
            analysis = await self._analyze_trends(all_trends)

            # Build final response
            current_time = datetime.now(timezone.utc)
            return {
                "success": True,
                "status": "OK",
                "data": {
                    "timestamp": current_time.isoformat(),
                    "total_trends": len(all_trends),
                    "trends": all_trends,
                    "analysis": analysis
                }
            }

        except Exception as e:
            logger.error(f"Error getting trending topics: {str(e)}")
            return {
                "success": False,
                "status": "ERROR",
                "error": str(e)
            }

    async def _analyze_trends(self, trends: List[Dict]) -> Dict:
        """Basic example to compute volume stats and identify top 10 trends by volume"""
        analysis = {
            "total_volume": 0,
            "max_volume": 0,
            "min_volume": float('inf'),
            "top_trends": []
        }

        for t in trends:
            vol = t.get("tweet_volume", 0) or 0
            analysis["total_volume"] += vol
            if vol > analysis["max_volume"]:
                analysis["max_volume"] = vol
            if vol > 0 and vol < analysis["min_volume"]:
                analysis["min_volume"] = vol

        if len(trends) == 0:
            # If no trends, set min_volume to 0
            analysis["min_volume"] = 0
        else:
            # Sort by descending tweet_volume
            sorted_by_vol = sorted(trends, key=lambda x: x.get("tweet_volume", 0) or 0, reverse=True)
            analysis["top_trends"] = sorted_by_vol[:10]

        return analysis

    async def get_topic_tweets(
        self,
        keyword: str,
        count: int,
        cursor: Optional[str] = None
    ) -> Dict:
        """Search tweets by keyword"""
        logger.info(f"Searching tweets for keyword: {keyword}")
        try:
            variables = {
                "rawQuery": keyword,
                "count": count * 2,  # Request more to account for filtering
                "cursor": cursor,
                "querySource": "typed_query",
                "product": "Top",
                "includePromotedContent": False,
                "withDownvotePerspective": False,
                "withReactionsMetadata": False,
                "withReactionsPerspective": False,
                "withSuperFollowsTweetFields": True,
                "withSuperFollowsUserFields": True,
                "withUserResults": True,
                "withBirdwatchPivots": False,
                "withReplyCount": True,
                "withVoice": True,
                "withV2Timeline": True
            }

            response = await self.graphql_request('SearchTimeline', variables)

            if not response or 'data' not in response:
                logger.error("No data found in search response")
                raise Exception("Failed to search tweets")

            # Extract tweets from response
            tweets = []
            next_cursor = None

            # Get timeline data with better error handling
            search_data = response.get('data', {})
            if not search_data:
                logger.error("No data found in search response")
                raise Exception("Search failed: No data in response")

            search_timeline = search_data.get('search_by_raw_query', {})
            if not search_timeline:
                logger.error("No search_by_raw_query found in response")
                raise Exception("Search failed: No search results found")

            timeline = search_timeline.get('search_timeline', {})
            if not timeline:
                logger.error("No search_timeline found in response")
                raise Exception("Search failed: No timeline data found")

            timeline_data = timeline.get('timeline', {})
            if not timeline_data:
                logger.error("No timeline data found in response")
                raise Exception("Search failed: Empty timeline")

            # Process instructions with validation
            instructions = timeline_data.get('instructions', [])
            if not instructions:
                logger.error("No instructions found in timeline")
                raise Exception("Search failed: No timeline instructions")

            logger.info(f"Processing {len(instructions)} timeline instructions")
            for instruction in instructions:
                if instruction.get('type') == 'TimelineAddEntries':
                    entries = instruction.get('entries', [])

                    for entry in entries:
                        if 'cursor-bottom-' in entry.get('entryId', ''):
                            next_cursor = entry.get('content', {}).get('value')
                            continue

                        content = entry.get('content', {})
                        if content.get('entryType') == 'TimelineTimelineItem':
                            item_content = content.get('itemContent', {})
                            tweet_results = item_content.get('tweet_results', {}).get('result', {})

                            if tweet_results:
                                processed_tweet = await self._process_tweet_data(tweet_results)
                                if processed_tweet:
                                    tweets.append(processed_tweet)

            # Sort tweets by time (newest first)
            tweets.sort(key=lambda x: datetime.strptime(x['created_at'], '%a %b %d %H:%M:%S %z %Y'), reverse=True)

            return {
                'tweets': tweets[:count],  # Limit to exactly what was requested
                'next_cursor': next_cursor if len(tweets) >= count else None,
                'keyword': keyword,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error searching tweets: {str(e)}")
            raise

    async def search_users(
        self,
        keyword: str,
        count: int,
        cursor: Optional[str] = None
    ) -> Dict:
        """Search users by keyword"""
        logger.info(f"Searching users for keyword: {keyword}")
        try:
            variables = {
                "searchMode": "People",
                "rawQuery": keyword,
                "count": count * 2,  # Request more to account for filtering
                "cursor": cursor,
                "querySource": "typed_query",
                "product": "People",
                "includePromotedContent": False,
                "withSuperFollowsUserFields": True,
                "withDownvotePerspective": False,
                "withReactionsMetadata": False,
                "withReactionsPerspective": False,
                "withUserResults": True,
                "withBirdwatchPivots": False,
                "withVoice": True,
                "withV2Timeline": True
            }

            response = await self.graphql_request('SearchTimeline', variables)

            if not response or 'data' not in response:
                logger.error("No data found in user search response")
                raise Exception("Failed to search users")

            # Extract users from response
            users = []
            next_cursor = None

            # Get timeline data with better error handling
            search_data = response.get('data', {})
            if not search_data:
                logger.error("No data found in user search response")
                raise Exception("Search failed: No data in response")

            search_timeline = search_data.get('search_by_raw_query', {})
            if not search_timeline:
                logger.error("No search_by_raw_query found in response")
                raise Exception("Search failed: No search results found")

            timeline = search_timeline.get('search_timeline', {})
            if not timeline:
                logger.error("No search_timeline found in response")
                raise Exception("Search failed: No timeline data found")

            timeline_data = timeline.get('timeline', {})
            if not timeline_data:
                logger.error("No timeline data found in response")
                raise Exception("Search failed: Empty timeline")

            # Process instructions with validation
            instructions = timeline_data.get('instructions', [])
            if not instructions:
                logger.error("No instructions found in timeline")
                raise Exception("Search failed: No timeline instructions")

            logger.info(f"Processing {len(instructions)} timeline instructions")
            for instruction in instructions:
                if instruction.get('type') == 'TimelineAddEntries':
                    entries = instruction.get('entries', [])

                    for entry in entries:
                        if 'cursor-bottom-' in entry.get('entryId', ''):
                            next_cursor = entry.get('content', {}).get('value')
                            continue

                        content = entry.get('content', {})
                        if content.get('entryType') == 'TimelineTimelineItem':
                            item_content = content.get('itemContent', {})
                            user_results = item_content.get('user_results', {}).get('result', {})

                            if user_results:
                                legacy = user_results.get('legacy', {})
                                professional = user_results.get('professional', {})

                                user = {
                                    'id': user_results.get('rest_id'),
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
                                    'verified_type': user_results.get('verified_type')
                                }
                                users.append(user)

            return {
                'users': users[:count],  # Limit to exactly what was requested
                'next_cursor': next_cursor if len(users) >= count else None,
                'keyword': keyword,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error searching users: {str(e)}")
            raise

    async def like_tweet(self, tweet_id: str) -> Dict:
        """Like a tweet"""
        logger.info(f"Liking tweet {tweet_id}")
        try:
            variables = {
                "tweet_id": str(tweet_id)
            }

            try:
                response = await self.graphql_request('FavoriteTweet', variables)

                # Check for errors in response
                if 'errors' in response:
                    error_msg = response['errors'][0].get('message', 'Unknown error')
                    logger.error(f"Failed to like tweet {tweet_id} - {error_msg}")
                    return {
                        "success": False,
                        "error": error_msg
                    }

                # Extract favorite data with multiple fallback paths
                favorite_data = None
                favorite_paths = [
                    lambda: response.get('data', {}).get('favorite_tweet'),
                    lambda: response.get('data', {}).get('favoriteTweet'),
                    lambda: response.get('favorite_tweet'),
                    lambda: response.get('favoriteTweet')
                ]

                for get_favorite in favorite_paths:
                    try:
                        data = get_favorite()
                        if data:
                            favorite_data = data
                            break
                    except Exception:
                        continue

                if favorite_data:
                    return {
                        "success": True,
                        "tweet_id": tweet_id,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }

                logger.error(f"Could not extract favorite data from response: {json.dumps(response, indent=2)}")
                return {
                    "success": False,
                    "error": "Failed to extract favorite data from response"
                }

            except Exception as e:
                logger.error(f"Error in GraphQL like: {str(e)}")
                return {
                    "success": False,
                    "error": str(e)
                }

        except Exception as e:
            logger.error(f"Error liking tweet {tweet_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def retweet(self, tweet_id: str) -> Dict:
        """Retweet a tweet"""
        logger.info(f"Retweeting tweet {tweet_id}")
        try:
            variables = {
                "tweet_id": str(tweet_id)
            }

            try:
                response = await self.graphql_request('CreateRetweet', variables)

                # Check for errors in response
                if 'errors' in response:
                    error_msg = response['errors'][0].get('message', 'Unknown error')
                    logger.error(f"Failed to retweet {tweet_id} - {error_msg}")
                    return {
                        "success": False,
                        "error": error_msg
                    }

                # Extract retweet data with multiple fallback paths
                retweet_data = None
                retweet_paths = [
                    lambda: response.get('data', {}).get('create_retweet'),
                    lambda: response.get('data', {}).get('createRetweet'),
                    lambda: response.get('create_retweet'),
                    lambda: response.get('createRetweet')
                ]

                for get_retweet in retweet_paths:
                    try:
                        data = get_retweet()
                        if data:
                            retweet_data = data
                            break
                    except Exception:
                        continue

                if retweet_data:
                    # Check retweet results with multiple fallback paths
                    retweet_results = None
                    result_paths = [
                        lambda: retweet_data.get('retweet_results'),
                        lambda: retweet_data.get('retweetResults'),
                        lambda: retweet_data.get('retweet'),
                        lambda: retweet_data
                    ]

                    for get_results in result_paths:
                        try:
                            data = get_results()
                            if data:
                                retweet_results = data
                                break
                        except Exception:
                            continue

                    if retweet_results:
                        logger.info(f"Successfully retweeted {tweet_id}")
                        return {
                            "success": True,
                            "tweet_id": tweet_id,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }

                logger.error(f"Could not extract retweet data from response: {json.dumps(response, indent=2)}")
                return {
                    "success": False,
                    "error": "Failed to extract retweet data from response"
                }

            except Exception as e:
                logger.error(f"Error in GraphQL retweet: {str(e)}")
                return {
                    "success": False,
                    "error": str(e)
                }

        except Exception as e:
            logger.error(f"Error retweeting {tweet_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def close(self):
        """Close HTTP client and cleanup transport"""
        if self.client:
            try:
                # Close any active connections
                await self.client.aclose()
            except Exception as e:
                logger.error(f"Error closing client: {str(e)}")
            finally:
                # Ensure transport is cleaned up
                if hasattr(self.client, 'transport'):
                    try:
                        await self.client.transport.aclose()
                    except Exception as e:
                        logger.error(f"Error closing transport: {str(e)}")
                self.client = None
