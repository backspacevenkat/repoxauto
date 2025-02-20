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
import hmac
import hashlib
import base64
from requests_oauthlib import OAuth1
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urljoin, urlparse, urlencode, parse_qsl

def construct_proxy_url(username: str, password: str, host: str, port: str) -> str:
    """Construct a proxy URL with proper encoding"""
    encoded_username = quote(str(username), safe='')
    encoded_password = quote(str(password), safe='')
    return f"http://{encoded_username}:{encoded_password}@{host}:{port}"

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

logger = logging.getLogger(__name__)

class TwitterClient:
    def __init__(
        self,
        account_no: str,
        auth_token: str,
        ct0: str,
        consumer_key: str = None,
        consumer_secret: str = None,
        bearer_token: str = None,
        access_token: str = None,
        access_token_secret: str = None,
        client_id: str = None,
        proxy_config: Optional[Dict[str, str]] = None,
        user_agent: Optional[str] = None
    ):
        """Initialize TwitterClient with authentication and configuration"""
        # Initialize instance variables
        self.account_no = account_no
        self.auth_token = auth_token
        self.ct0 = ct0
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.bearer_token = bearer_token
        self.access_token = access_token
        self.access_token_secret = access_token_secret
        self.client_id = client_id
        self.proxy_config = proxy_config
        
        # Initialize HTTP client
        self.client = None
        
        # Configure proxy if provided
        self.proxy_url = None
        if proxy_config:
            try:
                # Extract proxy details with correct keys
                username = proxy_config.get('proxy_username')
                password = proxy_config.get('proxy_password')
                host = proxy_config.get('proxy_url')
                port = proxy_config.get('proxy_port')

                # Validate all required fields
                if not all([username, password, host, port]):
                    missing = []
                    if not username: missing.append('proxy_username')
                    if not password: missing.append('proxy_password')
                    if not host: missing.append('proxy_url')
                    if not port: missing.append('proxy_port')
                    logger.error(f"Missing proxy configuration fields: {', '.join(missing)}")
                    raise ValueError(f"Missing proxy configuration: {', '.join(missing)}")

                # Construct proxy URL
                self.proxy_url = construct_proxy_url(
                    username=str(username),
                    password=str(password),
                    host=str(host),
                    port=str(port)
                )

                # Validate constructed URL
                parsed = urlparse(self.proxy_url)
                if not parsed.scheme or not parsed.hostname or not parsed.port:
                    raise ValueError("Invalid proxy URL format after construction")

                logger.info(f"Successfully configured proxy for account {account_no}")
                
            except Exception as e:
                logger.error(f"Failed to configure proxy for account {account_no}: {str(e)}")
                self.proxy_url = None
        
        # Set default user agent if none provided
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/91.0.4472.124 Safari/537.36"
        )
        
        # Initialize headers
        self.headers = {
            'authorization': f'Bearer {self.bearer_token}',
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-client-language': 'en',
            'x-twitter-active-user': 'yes',
            'content-type': 'application/json',
            'x-csrf-token': self.ct0,
            'cookie': f'auth_token={self.auth_token}; ct0={self.ct0}'
        }
        
        # API v2 specific headers
        self.api_v2_headers = {
            'authorization': f'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
            'content-type': 'application/json',
            'cookie': f'auth_token={self.auth_token}; ct0={self.ct0}',
            'x-csrf-token': self.ct0,
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-client-language': 'en',
            'x-twitter-active-user': 'yes'
        }
        
        # GraphQL specific headers
        self.graphql_headers = {
            'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
            'x-csrf-token': self.ct0, 
            'cookie': f'auth_token={self.auth_token}; ct0={self.ct0}',
            'content-type': 'application/json',
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-client-language': 'en',
            'x-twitter-active-user': 'yes',
            'Referer': 'https://x.com/',
            'User-Agent': self.user_agent,
            'accept': '*/*',
            'Accept': '*/*'
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
            "responsive_web_media_download_video_enabled": True,
            "hidden_profile_subscriptions_enabled": True,
            "profile_label_improvements_pcf_label_in_post_enabled": True, 
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "subscriptions_verification_info_is_identity_verified_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "highlights_tweets_tab_ui_enabled": True,
            "responsive_web_twitter_article_notes_tab_enabled": True,
            "subscriptions_feature_can_gift_premium": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "hidden_profile_subscriptions_enabled": True,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "highlights_tweets_tab_ui_enabled": True,
            "responsive_web_twitter_article_notes_tab_enabled": True,
            "subscriptions_feature_can_gift_premium": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "premium_content_api_read_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
            "responsive_web_grok_analyze_post_followups_enabled": False,
            "responsive_web_grok_share_attachment_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "premium_content_api_read_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
            "responsive_web_grok_analyze_post_followups_enabled": False,
            "responsive_web_grok_share_attachment_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "premium_content_api_read_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
            "responsive_web_grok_analyze_post_followups_enabled": False,
            "responsive_web_grok_share_attachment_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "premium_content_api_read_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
            "responsive_web_grok_analyze_post_followups_enabled": False,
            "responsive_web_grok_share_attachment_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "premium_content_api_read_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
            "responsive_web_grok_analyze_post_followups_enabled": False,
            "responsive_web_grok_share_attachment_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "premium_content_api_read_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
            "responsive_web_grok_analyze_post_followups_enabled": False,
            "responsive_web_grok_share_attachment_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "premium_content_api_read_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
            "responsive_web_grok_analyze_post_followups_enabled": False,
            "responsive_web_grok_share_attachment_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
            "premium_content_api_read_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
            "responsive_web_grok_analyze_post_followups_enabled": False,
            "responsive_web_grok_share_attachment_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "articles_preview_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_enhance_cards_enabled": False,





        }
        
        # GraphQL endpoint IDs
        self.GRAPHQL_ENDPOINTS = {
            'CreateTweet': '5radHM13Uo_czv5X3nnYNw',
            'DeleteTweet': 'VaenaVgh5q5ih7kvyVjgtg',
            'FavoriteTweet': 'lI07N6Otwv1PhnEgXILM7A',
            'CreateRetweet': 'ojPdsZsimiJrUGLR1sjUtA',
            'UserByScreenName': 'QGIw94L0abhuohrr76cSbw', 
            'UserByRestId': 'LWxkCeL8Hlx0-f24DmPAJw',
            'UserTweets': 'vBkRERAc5aGHAIuB7yFkRg',
            'UserTweetsAndReplies': 'bNSQNM4Pi1GwKGlpaKaQuw',
            'TweetDetail': 'LG_-V6iikp5XQKoH1tSg6A',
            'SearchTimeline': 'QGMTWxm841rbDndB-yQhIw',
            'HomeTimeline': 'qDTmVShVcZWv-Q6l0dSqmw',
            'ListLatestTweetsTimeline': 'ROoq1i-X-fJIWAOgc3PfxA',
            'SendDM': 'D8Jz2PBwsPKGjsDxNOYFmg',
            'DMInbox': 'B6Cj9rGwz4qHxB3Kz4KxgA',
            'DMTyping': 'Ozw6V5ayEw_Zk0_kbUn9Dw'
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
                    proxy_url = httpx.URL(self.proxy_url)
                    transport = httpx.AsyncHTTPTransport(
                        proxy=proxy_url,
                        verify=False,
                        retries=2,
                        trust_env=False
                    )
                    client_config["transport"] = transport
                    
                except Exception as e:
                    logger.error(f"Failed to configure proxy for account {self.account_no}: {str(e)}")
                    self.proxy_url = None
                    raise ValueError(f"Failed to configure proxy: {str(e)}")

            # Initialize client
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
        json_data: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        files: Optional[Dict] = None,
        data: Optional[Dict] = None
    ) -> Dict:
        """Make HTTP request with proper OAuth handling and minimal delays"""
        try:
            # Initialize client if needed
            if not self.client or self.client.is_closed:
                await self._init_client()
            
            if not self.client:
                raise Exception("Failed to initialize HTTP client")

            # Handle parameters without double encoding
            if params:
                params = {k: v for k, v in params.items()}

            # Add small random delay between requests
            await self._add_request_delay()

            # Select appropriate headers based on URL and request type
            request_headers = {}
            
            if 'upload.twitter.com' in url:
                # For media uploads, only oauth_* parameters in signature
                oauth_params = {
                    'oauth_consumer_key': self.consumer_key,
                    'oauth_nonce': generate_nonce(),
                    'oauth_signature_method': 'HMAC-SHA1',
                    'oauth_timestamp': str(int(time.time())),
                    'oauth_token': self.access_token,
                    'oauth_version': '1.0'
                }
                
                signature = generate_oauth_signature(
                    method,
                    url,
                    oauth_params,  # Only oauth params for signature
                    self.consumer_secret,
                    self.access_token_secret
                )
                oauth_params['oauth_signature'] = signature
                
                auth_header = 'OAuth ' + ', '.join(
                    f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                    for k, v in sorted(oauth_params.items())
                )
                
                request_headers = {
                    'Authorization': auth_header,
                    'Accept': 'application/json'
                }
                
            elif 'api.twitter.com/2/' in url:
                # API v2 endpoints with OAuth 1.0a
                oauth_params = {
                    'oauth_consumer_key': self.consumer_key,
                    'oauth_nonce': generate_nonce(),
                    'oauth_signature_method': 'HMAC-SHA1',
                    'oauth_timestamp': str(int(time.time())),
                    'oauth_token': self.access_token,
                    'oauth_version': '1.0'
                }
                
                # For API v2, only sign OAuth params
                signature = generate_oauth_signature(
                    method,
                    url,
                    oauth_params,
                    self.consumer_secret,
                    self.access_token_secret
                )
                oauth_params['oauth_signature'] = signature
                
                auth_header = 'OAuth ' + ', '.join(
                    f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                    for k, v in sorted(oauth_params.items())
                )
                
                request_headers = {
                    'Authorization': auth_header,
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                }
                
            elif 'api.twitter.com/1.1/' in url:
                # API v1.1 endpoints with OAuth 1.0a including params
                oauth_params = {
                    'oauth_consumer_key': self.consumer_key,
                    'oauth_nonce': generate_nonce(),
                    'oauth_signature_method': 'HMAC-SHA1',
                    'oauth_timestamp': str(int(time.time())),
                    'oauth_token': self.access_token,
                    'oauth_version': '1.0'
                }
                
                # Combine OAuth params with request params for signature
                all_params = {**oauth_params}
                if params:
                    all_params.update(params)
                if json_data:
                    # Flatten nested JSON for OAuth signature
                    flat_data = {}
                    for k, v in json_data.items():
                        if isinstance(v, dict):
                            for sub_k, sub_v in v.items():
                                flat_data[f"{k}.{sub_k}"] = str(sub_v)
                        else:
                            flat_data[k] = str(v)
                    all_params.update(flat_data)
                    
                signature = generate_oauth_signature(
                    method,
                    url,
                    all_params,
                    self.consumer_secret,
                    self.access_token_secret
                )
                oauth_params['oauth_signature'] = signature
                
                auth_header = 'OAuth ' + ', '.join(
                    f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                    for k, v in sorted(oauth_params.items())
                )
                
                request_headers = {
                    'Authorization': auth_header,
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                }
                
            elif 'twitter.com/i/api/graphql' in url:
                request_headers = self.graphql_headers.copy()

            # Add dynamic headers
            request_headers.update({
                'User-Agent': self.user_agent,
                'x-client-uuid': str(uuid.uuid4()),
                'accept-language': 'en-US,en;q=0.9'
            })

            # Add any custom headers
            if headers:
                request_headers.update(headers)

            # Prepare request kwargs
            request_kwargs = {
                'method': method,
                'url': url,
                'params': params,
                'headers': request_headers,
                'follow_redirects': True
            }

            # Handle files and data appropriately
            if files:
                if data:
                    # Combine files and form data
                    multipart_data = {}
                    for key, value in data.items():
                        multipart_data[key] = (None, str(value))
                    multipart_data.update(files)
                    request_kwargs['files'] = multipart_data
                else:
                    request_kwargs['files'] = files
                # Remove content-type for multipart
                if 'Content-Type' in request_kwargs['headers']:
                    del request_kwargs['headers']['Content-Type']
            elif data:
                request_kwargs['data'] = data
            elif json_data:
                request_kwargs['json'] = json_data

            # Make request with retries
            MAX_RETRIES = 3
            retry_count = 0
            
            while retry_count < MAX_RETRIES:
                try:
                    response = await self.client.request(**request_kwargs)
                    
                    # Handle rate limiting
                    if response.status_code == 429:
                        # Always wait 15 minutes for rate limits
                        retry_after = 900  # 15 minutes in seconds
                        logger.warning(f'Rate limited. Waiting {retry_after} seconds (15 minutes)...')
                        await asyncio.sleep(retry_after)
                        retry_count += 1
                        continue

                    # Handle auth errors
                    if response.status_code in (401, 403):
                        logger.error(f'Authentication failed: {response.text}')
                        raise Exception('Authentication failed - check credentials')

                    # Handle successful responses
                    if response.status_code == 204:  # No Content
                        return {}
                        
                    response.raise_for_status()
                    
                    try:
                        return response.json()
                    except json.JSONDecodeError:
                        if response.content:
                            logger.warning(f'Could not decode JSON response: {response.content[:200]}')
                        return {}

                except httpx.TimeoutException:
                    logger.warning(f'Request timeout (attempt {retry_count + 1}/{MAX_RETRIES})')
                    retry_count += 1
                    if retry_count < MAX_RETRIES:
                        await asyncio.sleep(2 ** retry_count)  # Exponential backoff
                    continue
                    
                except Exception as e:
                    logger.error(f'Request error: {str(e)}')
                    raise

            raise Exception(f'Request failed after {MAX_RETRIES} retries')

        except Exception as e:
            logger.error(f'Error in _make_request: {str(e)}')
            raise

    async def quote_tweet(
        self,
        tweet_id: str,
        text_content: str,
        media: Optional[str] = None
    ) -> Dict:
        """Create a quote tweet with OAuth 1.0a credentials"""
        logger.info(f"Quote tweeting tweet {tweet_id} with text '{text_content}'")
        endpoint = "https://api.twitter.com/2/tweets"

        try:
            # Upload media if provided
            media_ids = []
            if media:
                media_paths = [path.strip() for path in media.split(',') if path.strip()]
                for media_path in media_paths:
                    # Check media paths in priority order
                    possible_paths = [
                        os.path.join('backend/media', os.path.basename(media_path)),  # backend/media/file.png
                        os.path.join('backend/media', media_path),                    # backend/media/subfolder/file.png
                        media_path                                                    # Direct path as fallback
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
                    uploaded_ids = await self.upload_media([media_path])
                    if uploaded_ids:
                        media_ids.extend(uploaded_ids)
                        logger.info(f"Uploaded media {media_path}: {uploaded_ids[0]}")
                    await asyncio.sleep(1)

            # The JSON body for quote tweet
            json_data = {
                "text": text_content,
                "quote_tweet_id": tweet_id
            }
            if media_ids:
                json_data["media"] = {"media_ids": media_ids}

            # Build OAuth params (nonce, timestamp, etc.)
            oauth_timestamp = str(int(time.time()))
            oauth_nonce = generate_nonce()

            oauth_params = {
                "oauth_consumer_key": self.consumer_key,
                "oauth_token": self.access_token,
                "oauth_signature_method": "HMAC-SHA1",
                "oauth_timestamp": oauth_timestamp,
                "oauth_nonce": oauth_nonce,
                "oauth_version": "1.0"
            }

            # Combine for signature
            # For the official /2/tweets, we typically only sign the OAuth parameters
            signature = generate_oauth_signature(
                method="POST",
                url=endpoint,
                params=oauth_params,  # Only sign OAuth params
                consumer_secret=self.consumer_secret,
                access_token_secret=self.access_token_secret
            )
            oauth_params["oauth_signature"] = signature

            # Build the Authorization header
            auth_header = "OAuth " + ", ".join(
                f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                for k, v in sorted(oauth_params.items())
            )

            # Minimal headers for OAuth 1.0a call
            request_headers = {
                "Authorization": auth_header,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": self.user_agent
            }

            try:
                response = await self._make_request(
                    method="POST",
                    url=endpoint,
                    json_data=json_data,
                    headers=request_headers
                )

                if "data" in response:
                    return {
                        "success": True,
                        "tweet_id": response["data"]["id"],
                        "text": response["data"]["text"],
                        "type": "quote_tweet"
                    }
                else:
                    logger.error(f"Unexpected response format: {response}")
                    return {
                        "success": False,
                        "error": "Invalid response format"
                    }

            except Exception as e:
                logger.error(f"Error making quote tweet request: {str(e)}")
                return {
                    "success": False,
                    "error": str(e)
                }

        except Exception as e:
            logger.error(f"Error in quote_tweet: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def reply_tweet(self, tweet_id: str, text_content: str, media: Optional[str] = None) -> Dict:
        """Reply to a tweet using Twitter API v2"""
        logger.info(f"Replying to tweet {tweet_id}")
        try:
            # Upload media if provided
            media_ids = []
            if media:
                media_paths = [path.strip() for path in media.split(',') if path.strip()]
                for media_path in media_paths:
                    # Try different path combinations
                    possible_paths = [
                        os.path.join(os.getcwd(), media_path),
                        os.path.join(os.getcwd(), 'backend', media_path),
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
                        
                    uploaded_ids = await self.upload_media([found_path])
                    if uploaded_ids:
                        media_ids.extend(uploaded_ids)

            # Prepare OAuth parameters
            oauth_params = {
                'oauth_consumer_key': self.consumer_key,
                'oauth_nonce': generate_nonce(),
                'oauth_signature_method': 'HMAC-SHA1',
                'oauth_timestamp': str(int(time.time())),
                'oauth_token': self.access_token,
                'oauth_version': '1.0'
            }

            # Prepare request data
            json_data = {
                "text": text_content,
                "reply": {
                    "in_reply_to_tweet_id": tweet_id
                }
            }

            if media_ids:
                json_data["media"] = {"media_ids": media_ids}

            # Generate signature with OAuth params only
            signature = generate_oauth_signature(
                "POST",
                "https://api.twitter.com/2/tweets",
                oauth_params,  # Only sign OAuth params
                self.consumer_secret,
                self.access_token_secret
            )
            oauth_params['oauth_signature'] = signature

            # Create Authorization header
            auth_header = "OAuth " + ", ".join(
                f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                for k, v in sorted(oauth_params.items())
            )

            # Make API v2 request with OAuth 1.0a (minimal headers)
            response = await self._make_request(
                "POST",
                "https://api.twitter.com/2/tweets",
                json_data=json_data,
                headers={
                    'Authorization': auth_header,
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                }
            )

            if response and 'data' in response:
                return {
                    "success": True,
                    "tweet_id": response['data'].get('id'),
                    "text": response['data'].get('text'),
                    "type": "reply_tweet"
                }

            return {
                "success": False,
                "error": "Failed to create reply tweet"
            }

        except Exception as e:
            logger.error(f"Error replying to tweet {tweet_id}: {str(e)}")
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
                    if not parsed.scheme or not parsed.hostname or not parsed.port:
                        raise ValueError(f"Invalid proxy URL format: missing scheme, hostname, or port")
                    
                    # Validate proxy URL components
                    if parsed.scheme not in ['http', 'https']:
                        raise ValueError(f"Invalid proxy scheme: {parsed.scheme}")
                    
                    if not parsed.username or not parsed.password:
                        raise ValueError("Missing proxy credentials")
                    
                    # Ensure port is valid
                    try:
                        port = int(parsed.port)
                        if port < 1 or port > 65535:
                            raise ValueError(f"Invalid port number: {port}")
                    except (TypeError, ValueError) as e:
                        raise ValueError(f"Invalid port: {str(e)}")
                    
                    # Configure transport with proxy
                    proxy_url = httpx.URL(self.proxy_url)
                    transport = httpx.AsyncHTTPTransport(
                        proxy=proxy_url,
                        verify=False,
                        retries=2,
                        trust_env=False
                    )
                    client_config["transport"] = transport
                    
                    # Log success (with masked credentials)
                    masked_url = f"{parsed.scheme}://*****:****@{parsed.hostname}:{parsed.port}"
                    logger.info(f"Proxy configured successfully for account {self.account_no}: {masked_url}")
                    
                except Exception as e:
                    logger.error(f"Failed to configure proxy for account {self.account_no}: {str(e)}")
                    self.proxy_url = None  # Clear invalid proxy URL
                    raise ValueError(f"Failed to configure proxy: {str(e)}")

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
        json_data: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        files: Optional[Dict] = None,
        data: Optional[Dict] = None
    ) -> Dict:
        """
        Fixed core request method with proper OAuth handling
        """
        try:
            # Initialize client if needed
            if not self.client or self.client.is_closed:
                await self._init_client()
            
            if not self.client:
                raise Exception("Failed to initialize HTTP client")

            # Convert string parameters to UTF-8
            if params:
                params = {
                    k: v.encode('utf-8').decode('utf-8') if isinstance(v, str) else v 
                    for k, v in params.items()
                }

            # Select appropriate headers based on URL and request type
            request_headers = {}
            
            if 'upload.twitter.com' in url:
                # For media uploads, only oauth_* parameters in signature
                oauth_params = {
                    'oauth_consumer_key': self.consumer_key,
                    'oauth_nonce': generate_nonce(),
                    'oauth_signature_method': 'HMAC-SHA1',
                    'oauth_timestamp': str(int(time.time())),
                    'oauth_token': self.access_token,
                    'oauth_version': '1.0'
                }
                
                signature = generate_oauth_signature(
                    method,
                    url,
                    oauth_params,  # Only oauth params for signature
                    self.consumer_secret,
                    self.access_token_secret
                )
                oauth_params['oauth_signature'] = signature
                
                auth_header = 'OAuth ' + ', '.join(
                    f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                    for k, v in sorted(oauth_params.items())
                )
                
                request_headers = {
                    'Authorization': auth_header,
                    'Accept': 'application/json'
                }
                
            elif 'api.twitter.com/2/' in url:
                # API v2 endpoints with OAuth 1.0a
                oauth_params = {
                    'oauth_consumer_key': self.consumer_key,
                    'oauth_nonce': generate_nonce(),
                    'oauth_signature_method': 'HMAC-SHA1',
                    'oauth_timestamp': str(int(time.time())),
                    'oauth_token': self.access_token,
                    'oauth_version': '1.0'
                }
                
                # For API v2, only sign OAuth params
                signature = generate_oauth_signature(
                    method,
                    url,
                    oauth_params,
                    self.consumer_secret,
                    self.access_token_secret
                )
                oauth_params['oauth_signature'] = signature
                
                auth_header = 'OAuth ' + ', '.join(
                    f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                    for k, v in sorted(oauth_params.items())
                )
                
                request_headers = {
                    'Authorization': auth_header,
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                }
                
            elif 'api.twitter.com/1.1/' in url:
                # API v1.1 endpoints with OAuth 1.0a including params
                oauth_params = {
                    'oauth_consumer_key': self.consumer_key,
                    'oauth_nonce': generate_nonce(),
                    'oauth_signature_method': 'HMAC-SHA1',
                    'oauth_timestamp': str(int(time.time())),
                    'oauth_token': self.access_token,
                    'oauth_version': '1.0'
                }
                
                # Combine OAuth params with request params for signature
                all_params = {**oauth_params}
                if params:
                    all_params.update(params)
                if json_data:
                    # Flatten nested JSON for OAuth signature
                    flat_data = {}
                    for k, v in json_data.items():
                        if isinstance(v, dict):
                            for sub_k, sub_v in v.items():
                                flat_data[f"{k}.{sub_k}"] = str(sub_v)
                        else:
                            flat_data[k] = str(v)
                    all_params.update(flat_data)
                    
                signature = generate_oauth_signature(
                    method,
                    url,
                    all_params,
                    self.consumer_secret,
                    self.access_token_secret
                )
                oauth_params['oauth_signature'] = signature
                
                auth_header = 'OAuth ' + ', '.join(
                    f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                    for k, v in sorted(oauth_params.items())
                )
                
                request_headers = {
                    'Authorization': auth_header,
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                }
                
            elif 'twitter.com/i/api/graphql' in url:
                request_headers = self.graphql_headers.copy()

            # Add dynamic headers
            request_headers.update({
                'User-Agent': self.user_agent,
                'x-client-uuid': str(uuid.uuid4()),
                'accept-language': random.choice([
                    'en-US,en;q=0.9',
                    'en-GB,en;q=0.9',
                    'en-CA,en;q=0.9'
                ])
            })

            # Add any custom headers
            if headers:
                request_headers.update(headers)

            # Prepare request kwargs
            request_kwargs = {
                'method': method,
                'url': url,
                'params': params,
                'headers': request_headers,
                'follow_redirects': True
            }

            # Handle files and data appropriately
            if files:
                if data:
                    # Combine files and form data
                    multipart_data = {}
                    for key, value in data.items():
                        multipart_data[key] = (None, str(value))
                    multipart_data.update(files)
                    request_kwargs['files'] = multipart_data
                else:
                    request_kwargs['files'] = files
                # Remove content-type for multipart
                if 'Content-Type' in request_kwargs['headers']:
                    del request_kwargs['headers']['Content-Type']
            elif data:
                request_kwargs['data'] = data
            elif json_data:
                request_kwargs['json'] = json_data

            # Make request with retries
            MAX_RETRIES = 3
            retry_count = 0
            
            while retry_count < MAX_RETRIES:
                try:
                    response = await self.client.request(**request_kwargs)
                    
                    # Handle rate limiting
                    if response.status_code == 429:
                        retry_after = int(response.headers.get('retry-after', '60'))
                        logger.warning(f'Rate limited. Waiting {retry_after} seconds...')
                        await asyncio.sleep(retry_after)
                        retry_count += 1
                        continue

                    # Handle auth errors
                    if response.status_code in (401, 403):
                        logger.error(f'Authentication failed: {response.text}')
                        raise Exception('Authentication failed - check credentials')

                    # Handle successful responses
                    if response.status_code == 204:  # No Content
                        return {}
                        
                    response.raise_for_status()
                    
                    try:
                        return response.json()
                    except json.JSONDecodeError:
                        if response.content:
                            logger.warning(f'Could not decode JSON response: {response.content[:200]}')
                        return {}

                except httpx.TimeoutException:
                    logger.warning(f'Request timeout (attempt {retry_count + 1}/{MAX_RETRIES})')
                    retry_count += 1
                    if retry_count < MAX_RETRIES:
                        await asyncio.sleep(2 ** retry_count)  # Exponential backoff
                    continue
                    
                except Exception as e:
                    logger.error(f'Request error: {str(e)}')
                    raise

            raise Exception(f'Request failed after {MAX_RETRIES} retries')

        except Exception as e:
            logger.error(f'Error in _make_request: {str(e)}')
            raise

    async def _add_request_delay(self):
        """Add a small random delay between requests to avoid rate limits"""
        delay = random.uniform(0.5, 2.0)
        await asyncio.sleep(delay)

    async def _handle_rate_limit(self, retry_after: int = 60):
        """Handle rate limiting"""
        logger.warning(f"Rate limited. Waiting {retry_after} seconds...")
        await asyncio.sleep(retry_after)

    async def graphql_request(
        self,
        endpoint_name: str,
        variables: Dict,
        features: Optional[Dict] = None
    ) -> Dict:
        """Make a GraphQL request with updated headers and error handling"""
        endpoint_id = self.GRAPHQL_ENDPOINTS.get(endpoint_name)
        if not endpoint_id:
            raise ValueError(f"Unknown GraphQL endpoint: {endpoint_name}")

        # Add small random delay to simulate human behavior
        await asyncio.sleep(random.uniform(1.5, 4.0))
        
        try:
            base_url = "https://x.com/i/api/graphql"
            
            # Update headers with new transaction ID and client UUID
            headers = self.graphql_headers.copy()
            headers.update({
                'x-client-transaction-id': f'client-tx-{uuid.uuid4()}',
                'x-client-uuid': str(uuid.uuid4())
            })

            if endpoint_name in ['FavoriteTweet', 'CreateRetweet', 'CreateTweet']:
                # For mutations
                json_data = {
                    "variables": variables,
                    "features": features or self.DEFAULT_FEATURES,
                    "queryId": endpoint_id
                }
                
                response = await self._make_request(
                    "POST",
                    f"{base_url}/{endpoint_id}/{endpoint_name}",
                    json_data=json_data,
                    headers=headers
                )
            else:
                # For queries
                variables_json = json.dumps(variables, ensure_ascii=False)
                features_json = json.dumps(features or self.DEFAULT_FEATURES, ensure_ascii=False)
                
                response = await self._make_request(
                    "GET",
                    f"{base_url}/{endpoint_id}/{endpoint_name}",
                    params={
                        "variables": variables_json,
                        "features": features_json
                    },
                    headers=headers
                )
            
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
            # Add rate limiting delay
            await asyncio.sleep(random.uniform(1.0, 2.0))

            # First get user ID from username
            try:
                user_id = await self.get_user_id(username)
                if not user_id:
                    raise Exception(f"Could not get user ID for {username}")
                logger.info(f"Found user ID {user_id} for {username}")
            except Exception as e:
                logger.error(f"Error getting user ID for {username}: {str(e)}")
                return {
                    'tweets': [],
                    'next_cursor': None,
                    'username': username,
                    'error': str(e)
                }

            # Add another small delay between requests
            await asyncio.sleep(random.uniform(0.5, 1.0))

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

            endpoint = 'UserTweets'  # Always use UserTweets to exclude replies
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

            # Get tweet result data with improved extraction
            result = None
            
            # Log the tweet data structure for debugging
            logger.info(f"Processing tweet data: {json.dumps(tweet_data, indent=2)}")
            
            # First try to get result from tweet_results path
            result = (
                tweet_data.get('tweet_results', {}).get('result', {}) or
                tweet_data.get('itemContent', {}).get('tweet_results', {}).get('result', {}) or
                tweet_data.get('content', {}).get('itemContent', {}).get('tweet_results', {}).get('result', {}) or
                tweet_data.get('tweet', {}) or
                tweet_data
            )
            
            if not result:
                logger.error("Could not find valid result data")
                return None
            
            # Extract legacy data with fallbacks
            legacy = result.get('legacy', {})
            
            # If no legacy data, try to extract from note_tweet
            if not legacy and result.get('note_tweet'):
                note_tweet = result['note_tweet'].get('note_tweet_results', {}).get('result', {})
                if note_tweet:
                    legacy = {
                        'full_text': note_tweet.get('text', ''),
                        'text': note_tweet.get('text', ''),
                        'id_str': result.get('rest_id'),
                        'created_at': result.get('created_at')
                    }
            
            # If still no legacy data, try to construct from result
            if not legacy:
                legacy = {
                    'full_text': (
                        result.get('full_text') or
                        result.get('text') or
                        result.get('tweet', {}).get('text', '')
                    ),
                    'id_str': (
                        result.get('rest_id') or
                        result.get('id_str') or
                        result.get('tweet', {}).get('rest_id')
                    ),
                    'created_at': (
                        result.get('created_at') or
                        result.get('tweet', {}).get('created_at')
                    )
                }
            
            # Add additional legacy fields if available
            legacy.update({
                'lang': result.get('lang'),
                'source': result.get('source'),
                'conversation_id_str': result.get('conversation_id_str'),
                'reply_count': result.get('reply_count', 0),
                'retweet_count': result.get('retweet_count', 0),
                'favorite_count': result.get('favorite_count', 0),
                'quote_count': result.get('quote_count', 0),
                'bookmark_count': result.get('bookmark_count', 0),
                'view_count': result.get('view_count', 0),
                'in_reply_to_status_id_str': result.get('in_reply_to_status_id_str'),
                'in_reply_to_screen_name': result.get('in_reply_to_screen_name')
            })
            
            # Verify essential fields
            if not all([
                legacy.get('full_text') or legacy.get('text'),
                legacy.get('id_str') or result.get('rest_id'),
                legacy.get('created_at')
            ]):
                logger.error("Missing essential tweet data")
                logger.error(f"Legacy data: {json.dumps(legacy, indent=2)}")
                return None

            if not legacy:
                logger.error("Could not find valid legacy data in tweet")
                logger.error(f"Tweet data structure: {json.dumps(tweet_data, indent=2)}")
                return None

            # Get author info with improved extraction
            author = None
            user_data = None
            
            # First try to get user data from core/user_results
            user_data = (
                result.get('core', {}).get('user_results', {}).get('result', {}) or
                result.get('user_results', {}).get('result', {}) or
                result.get('user', {}) or
                legacy.get('user', {})
            )
            
            if user_data:
                # Try to get screen_name from user data
                author = (
                    user_data.get('legacy', {}).get('screen_name') or
                    user_data.get('screen_name')
                )
            
            # If no author found, try additional paths
            if not author:
                author = (
                    result.get('user', {}).get('screen_name') or
                    result.get('user_data', {}).get('screen_name') or
                    result.get('tweet', {}).get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {}).get('screen_name') or
                    legacy.get('user', {}).get('screen_name') or
                    legacy.get('screen_name')
                )
            
            # Log author extraction details
            logger.info(f"Author extraction: Found user data: {bool(user_data)}, Found author: {bool(author)}")
            if author:
                logger.info(f"Successfully extracted author: {author}")
            else:
                logger.error("Failed to extract author")
                logger.error(f"Available paths: user_data: {bool(user_data)}, "
                           f"legacy.user: {bool(legacy and 'user' in legacy)}, "
                           f"result.user: {bool(result and 'user' in result)}")
                
                # Try one last time with raw tweet data
                try:
                    raw_user_data = tweet_data.get('user', {})
                    if raw_user_data:
                        author = raw_user_data.get('screen_name')
                        if author:
                            logger.info(f"Found author from raw tweet data: {author}")
                except Exception as e:
                    logger.error(f"Error extracting author from raw data: {str(e)}")

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
        """Get trending topics using GraphQL endpoint"""
        logger.info("Fetching trending topics using GraphQL...")
        try:
            variables = {
                "rawQuery": "trending",
                "count": 40,
                "querySource": "explore_trending",
                "product": "Top",
                "withDownvotePerspective": False,
                "withReactionsMetadata": False,
                "withReactionsPerspective": False,
                "withSuperFollowsTweetFields": True,
                "withSuperFollowsUserFields": True,
                "withUserResults": True,
                "withBirdwatchPivots": False,
                "withReplyCount": True,
                "withTweetQuoteCount": True,
                "withTweetResult": True,
                "withVoice": True,
                "withV2Timeline": True,
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
                "referrer": "explore",
                "withQuotedTweetResultByRestId": True,
                "withBirdwatchNotes": True
            }

            response = await self.graphql_request('SearchTimeline', variables)
            
            if not response or 'data' not in response:
                raise Exception("Failed to get trending topics")

            # Extract trends from response
            trends = []
            timeline = response.get('data', {}).get('search_by_raw_query', {}).get('search_timeline', {})
            
            if not timeline:
                return {
                    "success": True,
                    "status": "OK",
                    "data": {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "total_trends": 0,
                        "trends": [],
                        "analysis": {
                            "total_volume": 0,
                            "max_volume": 0,
                            "min_volume": 0,
                            "top_trends": []
                        }
                    }
                }

            # Process timeline entries
            for entry in timeline.get('timeline', {}).get('instructions', []):
                if entry.get('type') == 'TimelineAddEntries':
                    for item in entry.get('entries', []):
                        content = item.get('content', {})
                        if content.get('entryType') == 'TimelineTimelineItem':
                            trend_item = content.get('itemContent', {}).get('trend', {})
                            if trend_item:
                                trends.append({
                                    "name": trend_item.get('name'),
                                    "tweet_volume": trend_item.get('tweet_volume', 0),
                                    "url": trend_item.get('url'),
                                    "location": "Worldwide",  # GraphQL only returns worldwide trends
                                    "as_of": datetime.now(timezone.utc).isoformat()
                                })

            # Sort trends by tweet volume
            trends.sort(key=lambda x: x.get('tweet_volume', 0) or 0, reverse=True)

            # Basic analysis
            analysis = {
                "total_volume": sum(t.get('tweet_volume', 0) or 0 for t in trends),
                "max_volume": max((t.get('tweet_volume', 0) or 0 for t in trends), default=0),
                "min_volume": min((t.get('tweet_volume', 0) or 0 for t in trends if t.get('tweet_volume', 0)), default=0),
                "top_trends": trends[:10]
            }

            return {
                "success": True,
                "status": "OK",
                "data": {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "total_trends": len(trends),
                    "trends": trends,
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

    async def _search_with_single_account(self, keyword: str, count: int, cursor: Optional[str] = None) -> Dict:
        """Fallback search using single account"""
        variables = {
            "rawQuery": keyword,
            "count": count,
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
        
        response = await self._make_graphql_request('SearchTimeline', variables)
        
        if not response or 'data' not in response:
            raise Exception("Failed to search tweets")
            
        timeline_data = (response.get('data', {})
            .get('search_by_raw_query', {})
            .get('search_timeline', {})
            .get('timeline', {}))
            
        if not timeline_data:
            raise Exception("No timeline data found")
            
        tweets = []
        next_cursor = None
        
        for instruction in timeline_data.get('instructions', []):
            if instruction.get('type') == 'TimelineAddEntries':
                for entry in instruction.get('entries', []):
                    if 'cursor-bottom-' in entry.get('entryId', ''):
                        next_cursor = entry.get('content', {}).get('value')
                        continue
                        
                    content = entry.get('content', {})
                    if content.get('entryType') == 'TimelineTimelineItem':
                        tweet_results = (content.get('itemContent', {})
                            .get('tweet_results', {})
                            .get('result', {}))
                        
                        if tweet_results:
                            processed_tweet = await self._process_tweet_data(tweet_results)
                            if processed_tweet:
                                tweets.append(processed_tweet)
                                
        sorted_tweets = sorted(
            tweets,
            key=lambda x: datetime.strptime(x['created_at'], '%a %b %d %H:%M:%S %z %Y'),
            reverse=True
        )
        
        return {
            'tweets': sorted_tweets[:count],
            'next_cursor': next_cursor if len(sorted_tweets) >= count else None,
            'keyword': keyword,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

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
        """Like a tweet using Twitter API v2 with OAuth 1.0a"""
        logger.info(f"Liking tweet {tweet_id}")
        try:
            # Get the numeric user ID from access token
            numeric_user_id = None
            if self.access_token and "-" in self.access_token:
                numeric_user_id = self.access_token.split("-")[0]
            
            if not numeric_user_id:
                raise Exception("Could not extract numeric user ID from access token")

            # The correct endpoint for likes with numeric user ID
            endpoint = f"https://api.twitter.com/2/users/{numeric_user_id}/likes"

            # Add initial delay for natural timing
            await asyncio.sleep(random.uniform(1.0, 3.0))

            # Prepare OAuth parameters
            oauth_params = {
                'oauth_consumer_key': self.consumer_key,
                'oauth_nonce': generate_nonce(),
                'oauth_signature_method': 'HMAC-SHA1',
                'oauth_timestamp': str(int(time.time())),
                'oauth_token': self.access_token,
                'oauth_version': '1.0'
            }

            # Generate signature
            signature = generate_oauth_signature(
                "POST",
                endpoint,
                oauth_params,  # Only sign OAuth params
                self.consumer_secret,
                self.access_token_secret
            )
            oauth_params['oauth_signature'] = signature

            # Create Authorization header
            auth_header = "OAuth " + ", ".join(
                f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                for k, v in sorted(oauth_params.items())
            )

            # Prepare request
            request_headers = {
                'Authorization': auth_header,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': self.user_agent,
                'x-client-transaction-id': f'client-{uuid.uuid4()}'
            }

            json_data = {
                "tweet_id": tweet_id
            }

            # Make the like request
            response = await self._make_request(
                method="POST",
                url=endpoint,
                json_data=json_data,
                headers=request_headers
            )

            # Check response
            if response and 'data' in response:
                liked = response['data'].get('liked', False)
                if liked:
                    logger.info(f"Successfully liked tweet {tweet_id}")
                    return {
                        "success": True,
                        "tweet_id": tweet_id,
                        "action": "like",
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
                "error": "Failed to like tweet - unknown error"
            }

        except Exception as e:
            logger.error(f"Error liking tweet {tweet_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def unlike_tweet(self, tweet_id: str) -> Dict:
        """Unlike a tweet using Twitter API v2 with OAuth 1.0a"""
        logger.info(f"Unliking tweet {tweet_id}")
        try:
            # Get the numeric user ID from access token
            numeric_user_id = None
            if self.access_token and "-" in self.access_token:
                numeric_user_id = self.access_token.split("-")[0]
            
            if not numeric_user_id:
                raise Exception("Could not extract numeric user ID from access token")

            # The correct endpoint for unlikes with numeric user ID
            endpoint = f"https://api.twitter.com/2/users/{numeric_user_id}/likes/{tweet_id}"

            # Add initial delay for natural timing
            await asyncio.sleep(random.uniform(1.0, 3.0))

            # Prepare OAuth parameters
            oauth_params = {
                'oauth_consumer_key': self.consumer_key,
                'oauth_nonce': generate_nonce(),
                'oauth_signature_method': 'HMAC-SHA1',
                'oauth_timestamp': str(int(time.time())),
                'oauth_token': self.access_token,
                'oauth_version': '1.0'
            }

            # Generate signature
            signature = generate_oauth_signature(
                "DELETE",
                endpoint,
                oauth_params,  # Only sign OAuth params
                self.consumer_secret,
                self.access_token_secret
            )
            oauth_params['oauth_signature'] = signature

            # Create Authorization header
            auth_header = "OAuth " + ", ".join(
                f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                for k, v in sorted(oauth_params.items())
            )

            # Prepare request
            request_headers = {
                'Authorization': auth_header,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': self.user_agent,
                'x-client-transaction-id': f'client-{uuid.uuid4()}'
            }

            # Make the unlike request
            response = await self._make_request(
                method="DELETE",
                url=endpoint,
                headers=request_headers
            )

            # Check response
            if response and 'data' in response:
                liked = not response['data'].get('liked', True)
                if liked:
                    logger.info(f"Successfully unliked tweet {tweet_id}")
                    return {
                        "success": True,
                        "tweet_id": tweet_id,
                        "action": "unlike",
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
                "error": "Failed to unlike tweet"
            }

        except Exception as e:
            logger.error(f"Error unliking tweet {tweet_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }


    async def _send_client_event(self, event_namespace: dict, items: list = None):
        """Send client event using proper endpoint and format"""
        
        if items is None:
            items = []
            
        event_data = {
            "_category_": "client_event",
            "format_version": 2,
            "triggered_on": int(time.time() * 1000),
            "items": items,
            "event_namespace": event_namespace,
            "client_event_sequence_start_timestamp": int(time.time() * 1000) - 1000,
            "client_event_sequence_number": random.randint(100, 300),
            "client_app_id": "3033300"
        }
        
        log_data = json.dumps([event_data])
        
        form_data = {
            'debug': 'true',
            'log': log_data
        }

        headers = {
            **self.graphql_headers,
            'content-type': 'application/x-www-form-urlencoded',
            'x-client-transaction-id': f'client-tx-{uuid.uuid4()}',
            'x-client-uuid': str(uuid.uuid4()),
            'origin': 'https://x.com',
            'referer': 'https://x.com/home'
        }

        await self._make_request(
            "POST",
            "https://x.com/i/api/1.1/jot/client_event.json",
            data=form_data,
            headers=headers
        )

    async def retweet(self, tweet_id: str) -> Dict:
        """Retweet using Twitter API v2 with OAuth 1.0a"""
        logger.info(f"Retweeting tweet {tweet_id}")
        try:
            # Get the numeric user ID from access token
            numeric_user_id = None
            if self.access_token and "-" in self.access_token:
                numeric_user_id = self.access_token.split("-")[0]
            
            if not numeric_user_id:
                raise Exception("Could not extract numeric user ID from access token")

            # The correct endpoint for retweets with numeric user ID
            endpoint = f"https://api.twitter.com/2/users/{numeric_user_id}/retweets"

            # Add initial delay for natural timing
            await asyncio.sleep(random.uniform(1.0, 3.0))

            # Prepare OAuth parameters
            oauth_params = {
                'oauth_consumer_key': self.consumer_key,
                'oauth_nonce': generate_nonce(),
                'oauth_signature_method': 'HMAC-SHA1',
                'oauth_timestamp': str(int(time.time())),
                'oauth_token': self.access_token,
                'oauth_version': '1.0'
            }

            # Generate signature
            signature = generate_oauth_signature(
                "POST",
                endpoint,
                oauth_params,  # Only sign OAuth params
                self.consumer_secret,
                self.access_token_secret
            )
            oauth_params['oauth_signature'] = signature

            # Create Authorization header
            auth_header = "OAuth " + ", ".join(
                f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                for k, v in sorted(oauth_params.items())
            )

            # Prepare request
            request_headers = {
                'Authorization': auth_header,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': self.user_agent,
                'x-client-transaction-id': f'client-{uuid.uuid4()}'
            }

            json_data = {
                "tweet_id": tweet_id
            }

            # Make the retweet request
            response = await self._make_request(
                method="POST",
                url=endpoint,
                json_data=json_data,
                headers=request_headers
            )

            # Check response
            if response and 'data' in response:
                retweeted = response['data'].get('retweeted', False)
                if retweeted:
                    logger.info(f"Successfully retweeted tweet {tweet_id}")
                    return {
                        "success": True,
                        "tweet_id": tweet_id,
                        "action": "retweet",
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
                "error": "Failed to retweet - unknown error"
            }

        except Exception as e:
            logger.error(f"Error retweeting {tweet_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def follow_user(self, user: str) -> Dict:
        """Follow a user using Twitter API v2 with OAuth 1.0a"""
        logger.info(f"Following user {user}")
        try:
            # First get user ID if username is provided
            target_user_id = None
            if not user.isdigit():
                # Get user ID from username
                variables = {
                    "screen_name": user,
                    "withSafetyModeUserFields": True
                }
                
                try:
                    response = await self.graphql_request('UserByScreenName', variables)
                    user_data = response.get('data', {}).get('user', {})
                    if not user_data:
                        return {
                            "success": False,
                            "error": f"User {user} not found"
                        }
                    
                    result = user_data.get('result', {})
                    target_user_id = result.get('rest_id')
                    if not target_user_id:
                        return {
                            "success": False,
                            "error": f"Could not get ID for user {user}"
                        }
                except Exception as e:
                    logger.error(f"Error getting user ID: {str(e)}")
                    return {
                        "success": False,
                        "error": f"Error getting user ID: {str(e)}"
                    }
            else:
                target_user_id = user

            # Get the numeric user ID from access token
            numeric_user_id = None
            if self.access_token and "-" in self.access_token:
                numeric_user_id = self.access_token.split("-")[0]
            
            if not numeric_user_id:
                raise Exception("Could not extract numeric user ID from access token")

            # The correct endpoint for following with numeric user ID
            endpoint = f"https://api.twitter.com/2/users/{numeric_user_id}/following"

            # Add initial delay for natural timing
            await asyncio.sleep(random.uniform(1.0, 3.0))

            # Prepare OAuth parameters
            oauth_params = {
                'oauth_consumer_key': self.consumer_key,
                'oauth_nonce': generate_nonce(),
                'oauth_signature_method': 'HMAC-SHA1',
                'oauth_timestamp': str(int(time.time())),
                'oauth_token': self.access_token,
                'oauth_version': '1.0'
            }

            # Generate signature
            signature = generate_oauth_signature(
                "POST",
                endpoint,
                oauth_params,
                self.consumer_secret,
                self.access_token_secret
            )
            oauth_params['oauth_signature'] = signature

            # Create Authorization header
            auth_header = "OAuth " + ", ".join(
                f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                for k, v in sorted(oauth_params.items())
            )

            # Prepare request
            request_headers = {
                'Authorization': auth_header,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': self.user_agent,
                'x-client-transaction-id': f'client-{uuid.uuid4()}'
            }

            json_data = {
                "target_user_id": target_user_id
            }

            # Make the follow request
            response = await self._make_request(
                method="POST",
                url=endpoint,
                json_data=json_data,
                headers=request_headers
            )

            # Check response
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
            logger.error(f"Error following user {target_user_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def send_dm(self, recipient_id: str, text: str, media: Optional[str] = None) -> Dict:
        """
        Send a DM via X/Twitter's internal DM endpoint (1.1/dm/new.json)
        NOTE: This version uses form data to match how the web client sends messages.
        """
        logger.info(f"Sending DM to user {recipient_id}")
        try:
            # If 'recipient_id' is actually a username, look up numeric user ID
            if not recipient_id.isdigit():
                recipient_id = await self.get_user_id(recipient_id)

            # Extract our own user ID from the OAuth1.0a access token (the part before the dash)
            # Example: "1861120839539646464-ABC123..." => sender_id = "1861120839539646464"
            sender_id = None
            if self.access_token and "-" in self.access_token:
                sender_id = self.access_token.split("-")[0]
            if not sender_id:
                logger.error("Could not extract sender ID from access_token.")
                return {"success": False, "error": "Invalid or missing access_token."}

            # Build the "conversation_id"
            # Typically, the conversation_id is the two user IDs in ascending order,
            # joined by a dash. If the UI shows "122356440-1861120839539646464.json",
            # that means the smaller user ID is first. We can replicate the same logic:
            user_ids = sorted([int(sender_id), int(recipient_id)])
            conversation_id = f"{user_ids[0]}-{user_ids[1]}"

            # (Optional) DM permissions check
            try:
                perms_url = "https://twitter.com/i/api/1.1/dm/permissions.json"
                perms_params = {"recipient_ids": recipient_id, "dm_users": "true"}
                await self._make_request(
                    method="GET",
                    url=perms_url,
                    params=perms_params,
                    headers={
                        **self.graphql_headers,
                        "cookie": f"auth_token={self.auth_token}; ct0={self.ct0}",
                        "x-csrf-token": self.ct0,
                        "referer": "https://twitter.com/messages",
                    },
                )
            except Exception as e:
                logger.warning(f"DM permissions check failed (often harmless if user never DMed before): {e}")

            # (Optional) conversation info check
            try:
                convo_url = f"https://twitter.com/i/api/1.1/dm/conversation/{conversation_id}.json"
                convo_params = {
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
                    "cards_platform": "Web-12",
                    "include_cards": "1",
                    "include_ext_alt_text": "true",
                    "include_quote_count": "true",
                    "include_reply_count": "1",
                    "tweet_mode": "extended",
                    "include_ext_views": "true",
                    "include_groups": "true",
                    "include_inbox_timelines": "true",
                    "include_ext_media_color": "true",
                    "supports_reactions": "true",
                    "include_conversation_info": "true",
                }
                await self._make_request(
                    method="GET",
                    url=convo_url,
                    params=convo_params,
                    headers={
                        **self.graphql_headers,
                        "cookie": f"auth_token={self.auth_token}; ct0={self.ct0}",
                        "x-csrf-token": self.ct0,
                        "referer": f"https://twitter.com/messages/{recipient_id}",
                    },
                )
            except Exception as e:
                logger.info(f"Conversation info request may fail if new conversation: {e}")

            # Handle media upload if provided
            media_id = None
            if media:
                found_path = None
                for p in [
                    os.path.join(os.getcwd(), media),
                    os.path.join(os.getcwd(), "backend", media),
                    media,
                ]:
                    if os.path.exists(p):
                        found_path = p
                        break
                if found_path:
                    # Override media category for DM uploads
                    original_category = self.get_media_info(found_path)['category']
                    if original_category == 'tweet_image':
                        self.get_media_info(found_path)['category'] = 'dm_image'
                    elif original_category == 'tweet_gif':
                        self.get_media_info(found_path)['category'] = 'dm_gif'
                    elif original_category == 'tweet_video':
                        self.get_media_info(found_path)['category'] = 'dm_video'
                    
                    uploaded_ids = await self.upload_media([found_path], for_dm=True)
                    if uploaded_ids:
                        media_id = uploaded_ids[0]
                else:
                    logger.error(f"Media file not found: {media}")

            # Set up the DM endpoint parameters
            dm_url = "https://twitter.com/i/api/1.1/dm/new.json"
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

            # Build form data
            form_data = {
                "conversation_id": conversation_id,
                "text": text,
            }
            if media_id:
                form_data["media_id"] = media_id

            # Set up final headers
            final_headers = {
                **self.graphql_headers,
                "cookie": f"auth_token={self.auth_token}; ct0={self.ct0}",
                "x-csrf-token": self.ct0,
                "referer": f"https://twitter.com/messages/{recipient_id}",
                "content-type": "application/x-www-form-urlencoded",
            }

            # Send the DM
            response = await self._make_request(
                method="POST",
                url=dm_url,
                params=dm_params,
                data=form_data,
                headers=final_headers,
            )

            # Handle response - check for both event-style and entries-style responses
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
                # Handle entries-style response
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

            # Only log as error if we didn't find a success indicator
            logger.error(f"Failed to send DM - response: {response}")
            if "errors" in response and response["errors"]:
                error_message = response["errors"][0].get("message", "Unknown error")
                return {"success": False, "error": error_message}
            return {"success": False, "error": "DM endpoint returned unexpected structure"}

        except Exception as e:
            logger.error(f"Error sending DM to {recipient_id}: {str(e)}")
            return {"success": False, "error": str(e)}

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
        """
        Update user profile settings using Twitter API v1.1 endpoints with OAuth 1.0a authentication
        """
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

                # Generate OAuth parameters for profile update
                oauth_params = {
                    'oauth_consumer_key': self.consumer_key,
                    'oauth_nonce': generate_nonce(),
                    'oauth_signature_method': 'HMAC-SHA1',
                    'oauth_timestamp': str(int(time.time())),
                    'oauth_token': self.access_token,
                    'oauth_version': '1.0'
                }
                
                # Include all parameters in signature
                all_params = {**oauth_params, **profile_data}
                signature = generate_oauth_signature(
                    'POST',
                    'https://api.twitter.com/1.1/account/update_profile.json',
                    all_params,
                    self.consumer_secret,
                    self.access_token_secret
                )
                oauth_params['oauth_signature'] = signature
                
                auth_header = 'OAuth ' + ', '.join(
                    f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                    for k, v in sorted(oauth_params.items())
                )

                profile_response = await self._make_request(
                    method="POST",
                    url="https://api.twitter.com/1.1/account/update_profile.json",
                    data=profile_data,
                    headers={
                        'Authorization': auth_header,
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'Accept': 'application/json'
                    }
                )
                responses['profile_update'] = profile_response

            # 2. Update language settings if provided
            if lang is not None:
                oauth_params = {
                    'oauth_consumer_key': self.consumer_key,
                    'oauth_nonce': generate_nonce(),
                    'oauth_signature_method': 'HMAC-SHA1',
                    'oauth_timestamp': str(int(time.time())),
                    'oauth_token': self.access_token,
                    'oauth_version': '1.0'
                }
                
                lang_data = {'lang': lang}
                all_params = {**oauth_params, **lang_data}
                signature = generate_oauth_signature(
                    'POST',
                    'https://api.twitter.com/1.1/account/settings.json',
                    all_params,
                    self.consumer_secret,
                    self.access_token_secret
                )
                oauth_params['oauth_signature'] = signature
                
                auth_header = 'OAuth ' + ', '.join(
                    f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                    for k, v in sorted(oauth_params.items())
                )

                settings_response = await self._make_request(
                    method="POST",
                    url="https://api.twitter.com/1.1/account/settings.json",
                    data=lang_data,
                    headers={
                        'Authorization': auth_header,
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'Accept': 'application/json'
                    }
                )
                responses['settings_update'] = settings_response

            # 3. Handle profile image update if provided
            if profile_image:
                # Get image data
                image_data = None
                if profile_image.startswith(('http://', 'https://')):
                    async with httpx.AsyncClient() as client:
                        response = await client.get(profile_image)
                        if response.status_code == 200:
                            image_data = response.content
                else:
                    # Check various local paths
                    possible_paths = [
                        profile_image,
                        os.path.join('backend', profile_image),
                        os.path.join(os.getcwd(), profile_image)
                    ]
                    
                    for path in possible_paths:
                        if os.path.exists(path):
                            with open(path, 'rb') as f:
                                image_data = f.read()
                            break

                if image_data:
                    # Generate OAuth parameters for image upload
                    oauth_params = {
                        'oauth_consumer_key': self.consumer_key,
                        'oauth_nonce': generate_nonce(),
                        'oauth_signature_method': 'HMAC-SHA1',
                        'oauth_timestamp': str(int(time.time())),
                        'oauth_token': self.access_token,
                        'oauth_version': '1.0'
                    }
                    
                    # For multipart uploads, only sign OAuth params
                    signature = generate_oauth_signature(
                        'POST',
                        'https://api.twitter.com/1.1/account/update_profile_image.json',
                        oauth_params,
                        self.consumer_secret,
                        self.access_token_secret
                    )
                    oauth_params['oauth_signature'] = signature
                    
                    auth_header = 'OAuth ' + ', '.join(
                        f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                        for k, v in sorted(oauth_params.items())
                    )

                    # Upload profile image
                    files = {
                        'image': ('image.jpg', image_data, 'image/jpeg')
                    }
                    
                    profile_image_response = await self._make_request(
                        method="POST",
                        url="https://api.twitter.com/1.1/account/update_profile_image.json",
                        files=files,
                        headers={
                            'Authorization': auth_header,
                            'Accept': 'application/json'
                        }
                    )
                    responses['profile_image_update'] = profile_image_response

            # 4. Handle profile banner update if provided
            if profile_banner:
                # Get banner data
                banner_data = None
                if profile_banner.startswith(('http://', 'https://')):
                    async with httpx.AsyncClient() as client:
                        response = await client.get(profile_banner)
                        if response.status_code == 200:
                            banner_data = response.content
                else:
                    # Check various local paths
                    possible_paths = [
                        profile_banner,
                        os.path.join('backend', profile_banner),
                        os.path.join(os.getcwd(), profile_banner)
                    ]
                    
                    for path in possible_paths:
                        if os.path.exists(path):
                            with open(path, 'rb') as f:
                                banner_data = f.read()
                            break

                if banner_data:
                    # Generate OAuth parameters for banner upload
                    oauth_params = {
                        'oauth_consumer_key': self.consumer_key,
                        'oauth_nonce': generate_nonce(),
                        'oauth_signature_method': 'HMAC-SHA1',
                        'oauth_timestamp': str(int(time.time())),
                        'oauth_token': self.access_token,
                        'oauth_version': '1.0'
                    }
                    
                    # For multipart uploads, only sign OAuth params
                    signature = generate_oauth_signature(
                        'POST',
                        'https://api.twitter.com/1.1/account/update_profile_banner.json',
                        oauth_params,
                        self.consumer_secret,
                        self.access_token_secret
                    )
                    oauth_params['oauth_signature'] = signature
                    
                    auth_header = 'OAuth ' + ', '.join(
                        f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                        for k, v in sorted(oauth_params.items())
                    )

                    # Upload banner image
                    files = {
                        'banner': ('banner.jpg', banner_data, 'image/jpeg')
                    }
                    
                    form_data = {
                        'width': '1500',
                        'height': '500',
                        'offset_left': '0',
                        'offset_top': '0'
                    }
                    
                    banner_response = await self._make_request(
                        method="POST",
                        url="https://api.twitter.com/1.1/account/update_profile_banner.json",
                        files=files,
                        data=form_data,
                        headers={
                            'Authorization': auth_header,
                            'Accept': 'application/json'
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
                        error_msg = response['errors'][0].get('message', 'Unknown error')
                        error_code = response['errors'][0].get('code')
                        
                        if error_code == 88:  # Rate limit
                            logger.error(f"Rate limit reached in {key}")
                            return {
                                "success": False,
                                "error": "Rate limit reached",
                                "rate_limited": True,
                                "retry_after": 900  # 15 minutes in seconds
                            }
                        elif error_code == 187:  # Duplicate content
                            logger.error(f"Duplicate content error in {key}")
                            return {
                                "success": False,
                                "error": "Profile update contains duplicate content"
                            }
                        elif error_code == 324:  # Image upload error
                            logger.error(f"Image upload error in {key}: {error_msg}")
                            return {
                                "success": False,
                                "error": f"Image upload failed: {error_msg}"
                            }
                        else:
                            logger.error(f"Error in {key}: {error_msg} (code: {error_code})")
                            return {
                                "success": False,
                                "error": f"Error in {key}: {error_msg}"
                            }

            # Handle username update separately if requested
            if new_login:
                from .browser_operations import change_username
                username_result = await change_username(
                    old_auth_token=self.auth_token,
                    old_ct0=self.ct0,
                    new_username=new_login,
                    proxy_config=self.proxy_config,
                    headless=False
                )
                
                responses['username_update'] = username_result
                if not username_result['success']:
                    return {
                        "success": False,
                        "error": f"Username update failed: {username_result.get('error', 'Unknown error')}"
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

    def generate_oauth_signature(self, method: str, url: str, params: Dict[str, str], 
                            consumer_secret: str, token_secret: str) -> str:
        """Generate OAuth 1.0a signature"""
        # Create parameter string
        sorted_params = sorted(params.items())
        param_string = '&'.join([
            f"{quote(str(k), safe='')}"
            f"="
            f"{quote(str(v), safe='')}"
            for k, v in sorted_params
        ])
        
        # Create signature base string
        signature_base = '&'.join([
            quote(method.upper(), safe=''),
            quote(url, safe=''),
            quote(param_string, safe='')
        ])
        
        # Create signing key
        signing_key = f"{quote(consumer_secret, safe='')}&{quote(token_secret or '', safe='')}"
        
        # Calculate HMAC-SHA1 signature
        hashed = hmac.new(
            signing_key.encode('utf-8'),
            signature_base.encode('utf-8'),
            hashlib.sha1
        )
        
        return base64.b64encode(hashed.digest()).decode('utf-8')

    async def unfollow_user(self, target_user_id: str) -> Dict:
        """Unfollow a user using Twitter API v2 with OAuth 1.0a"""
        logger.info(f"Unfollowing user {target_user_id}")
        try:
            # Get the numeric user ID from access token
            numeric_user_id = None
            if self.access_token and "-" in self.access_token:
                numeric_user_id = self.access_token.split("-")[0]
            
            if not numeric_user_id:
                raise Exception("Could not extract numeric user ID from access token")

            # The correct endpoint for unfollowing with numeric user ID
            endpoint = f"https://api.twitter.com/2/users/{numeric_user_id}/following/{target_user_id}"

            # Add initial delay for natural timing
            await asyncio.sleep(random.uniform(1.0, 3.0))

            # Prepare OAuth parameters
            oauth_params = {
                'oauth_consumer_key': self.consumer_key,
                'oauth_nonce': generate_nonce(),
                'oauth_signature_method': 'HMAC-SHA1',
                'oauth_timestamp': str(int(time.time())),
                'oauth_token': self.access_token,
                'oauth_version': '1.0'
            }

            # Generate signature
            signature = generate_oauth_signature(
                "DELETE",
                endpoint,
                oauth_params,
                self.consumer_secret,
                self.access_token_secret
            )
            oauth_params['oauth_signature'] = signature

            # Create Authorization header
            auth_header = "OAuth " + ", ".join(
                f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                for k, v in sorted(oauth_params.items())
            )

            # Prepare request
            request_headers = {
                'Authorization': auth_header,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': self.user_agent,
                'x-client-transaction-id': f'client-{uuid.uuid4()}'
            }

            # Make the unfollow request
            response = await self._make_request(
                method="DELETE",
                url=endpoint,
                headers=request_headers
            )

            # Check response
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

    async def _raw_post(
        self,
        url: str,
        data: Dict = None,
        files: Dict = None,
        headers: Dict = None,
        params: Dict = None
    ) -> dict:
        """
        Improved raw POST request handler with better multipart and OAuth support
        """
        try:
            if not self.client:
                await self._init_client()

            # Start with empty headers if none provided
            request_headers = headers or {}
            
            # Handle User-Agent and common headers
            request_headers.update({
                'User-Agent': self.user_agent,
                'Accept': 'application/json'
            })

            # Build request kwargs
            request_kwargs = {
                "method": "POST",
                "url": url,
                "headers": request_headers,
                "follow_redirects": True
            }

            # Handle query parameters
            if params:
                request_kwargs["params"] = params

            # Handle files upload (multipart/form-data)
            if files:
                if data:
                    # If both files and form data, combine them for multipart request
                    multipart_data = {}
                    # Add regular form fields
                    for key, value in data.items():
                        multipart_data[key] = (None, str(value))
                    # Add files
                    multipart_data.update(files)
                    request_kwargs["files"] = multipart_data
                else:
                    request_kwargs["files"] = files
                    
                # For multipart, don't set Content-Type header - let httpx set it with boundary
                if 'Content-Type' in request_headers:
                    del request_headers['Content-Type']
                    
            # Handle form data without files
            elif data:
                if isinstance(data, dict):
                    # Check if we're dealing with URL-encoded form data
                    if headers and headers.get('Content-Type') == 'application/x-www-form-urlencoded':
                        request_kwargs["data"] = data
                    else:
                        # Default to JSON if no specific content type
                        request_kwargs["json"] = data
                else:
                    request_kwargs["data"] = data

            # Make the request with proper error handling
            resp = await self.client.request(**request_kwargs)
            
            # Handle different response status codes
            if resp.status_code == 204:  # No Content
                return {}
            elif resp.status_code == 200:  # OK with content
                try:
                    return resp.json()
                except json.JSONDecodeError:
                    if resp.content:
                        logger.warning(f"Could not decode JSON response: {resp.content[:200]}")
                    return {}
            elif resp.status_code == 401:  # Unauthorized
                logger.error(f"Authentication failed: {resp.text}")
                raise Exception("Authentication failed - check credentials")
            elif resp.status_code == 400:  # Bad Request
                logger.error(f"Bad request error: {resp.text}")
                raise Exception(f"Bad request: {resp.text}")
            else:
                logger.error(f"Bad status code: {resp.status_code}")
                logger.error(f"Response text: {resp.text}")
                raise Exception(f"Request failed with status {resp.status_code}")

        except httpx.TimeoutException:
            logger.error("Request timed out")
            raise Exception("Request timed out")
        except httpx.NetworkError as e:
            logger.error(f"Network error: {str(e)}")
            raise Exception(f"Network error: {str(e)}")
        except Exception as e:
            logger.error(f"Error in _raw_post: {str(e)}")
            raise

    async def _raw_get(
        self,
        url: str,
        params: Dict = None,
        headers: Dict = None
    ) -> dict:
        """
        Improved raw GET request handler with better error handling
        """
        try:
            if not self.client:
                await self._init_client()

            # Build headers
            request_headers = headers or {}
            request_headers.update({
                'User-Agent': self.user_agent,
                'Accept': 'application/json'
            })

            # Make request
            resp = await self.client.request(
                method="GET",
                url=url,
                params=params or {},
                headers=request_headers,
                follow_redirects=True
            )

            # Handle response
            if resp.status_code in (200, 201, 202):
                try:
                    return resp.json()
                except json.JSONDecodeError:
                    if resp.content:
                        logger.warning(f"Could not decode JSON response: {resp.content[:200]}")
                    return {}
            elif resp.status_code == 401:
                logger.error(f"Authentication failed: {resp.text}")
                raise Exception("Authentication failed - check credentials")
            else:
                logger.error(f"Bad GET status code: {resp.status_code}")
                logger.error(f"Response text: {resp.text}")
                raise Exception(f"GET request failed with status {resp.status_code}")

        except httpx.TimeoutException:
            logger.error("GET request timed out")
            raise Exception("GET request timed out")
        except httpx.NetworkError as e:
            logger.error(f"Network error in GET request: {str(e)}")
            raise Exception(f"Network error in GET request: {str(e)}")
        except Exception as e:
            logger.error(f"Error in _raw_get: {str(e)}")
            raise

    async def _poll_video_status(self, media_id: str, attempts: int = 5):
        """
        Poll for status of an async video/gif upload every few seconds until 'succeeded' or 'failed'.
        For large videos/GIF, Twitter returns 'processing_info' so we must poll until done.
        """
        check_url = "https://upload.twitter.com/1.1/media/upload.json"

        for attempt in range(attempts):
            await asyncio.sleep(2)
            # sign again
            oauth_params = {
                'oauth_consumer_key': self.consumer_key,
                'oauth_nonce': generate_nonce(),
                'oauth_signature_method': 'HMAC-SHA1',
                'oauth_timestamp': str(int(time.time())),
                'oauth_token': self.access_token,
                'oauth_version': '1.0'
            }
            signature = generate_oauth_signature(
                "GET",
                check_url,
                oauth_params,
                self.consumer_secret,
                self.access_token_secret
            )
            oauth_params['oauth_signature'] = signature

            auth_header = 'OAuth ' + ', '.join(
                f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                for k, v in sorted(oauth_params.items())
            )

            status_params = {
                'command': 'STATUS',
                'media_id': media_id
            }

            resp = await self._raw_get(
                url=check_url,
                params=status_params,
                headers={'Authorization': auth_header}
            )
            if not resp:
                logger.error("No status response, can't poll.")
                return

            processing_info = resp.get('processing_info', {})
            if not processing_info:
                logger.info("No processing_info. Presumably done.")
                return

            state = processing_info.get('state')
            logger.info(f"processing_info -> state={state}")
            if state == 'succeeded':
                return
            elif state == 'failed':
                error_msg = processing_info.get('error', {})
                logger.error(f"Media processing failed: {error_msg}")
                return
            else:
                check_after = processing_info.get('check_after_secs', 3)
                logger.info(f"Waiting {check_after}s to re-check ...")
                await asyncio.sleep(check_after)

    async def upload_media(self, media_paths: List[str], for_dm: bool = False) -> List[str]:
        """Fixed implementation matching working example's APPEND format with DM support"""
        logger.info(f"Uploading {len(media_paths)} media files")
        media_ids = []
        
        if not self.client or self.client.is_closed:
            await self._init_client()
        
        if not self.client:
            raise Exception("Failed to initialize HTTP client")
        
        UPLOAD_ENDPOINT = 'https://upload.twitter.com/1.1/media/upload.json'
        
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

                # Generate OAuth signature for INIT
                oauth_params = {
                    'oauth_consumer_key': self.consumer_key,
                    'oauth_nonce': generate_nonce(),
                    'oauth_signature_method': 'HMAC-SHA1',
                    'oauth_timestamp': str(int(time.time())),
                    'oauth_token': self.access_token,
                    'oauth_version': '1.0'
                }
                
                # Include all parameters in signature for INIT
                all_params = {**oauth_params, **init_data}
                signature = generate_oauth_signature(
                    'POST',
                    UPLOAD_ENDPOINT,
                    all_params,
                    self.consumer_secret,
                    self.access_token_secret
                )
                oauth_params['oauth_signature'] = signature
                
                auth_header = 'OAuth ' + ', '.join(
                    f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                    for k, v in sorted(oauth_params.items())
                )

                init_response = await self.client.post(
                    UPLOAD_ENDPOINT,
                    data=init_data,
                    headers={
                        'Authorization': auth_header,
                        'Content-Type': 'application/x-www-form-urlencoded'
                    }
                )
                
                if init_response.status_code not in (200, 201, 202):
                    logger.error(f"INIT failed with status {init_response.status_code}: {init_response.text}")
                    continue

                init_json = init_response.json()
                media_id = init_json.get('media_id_string')
                if not media_id:
                    logger.error("No media_id in INIT response")
                    continue

                logger.info(f"INIT successful: {media_id}")

                # APPEND phase
                with open(media_path, 'rb') as f:
                    chunk = f.read()

                # New OAuth params for APPEND
                oauth_params = {
                    'oauth_consumer_key': self.consumer_key,
                    'oauth_nonce': generate_nonce(),
                    'oauth_signature_method': 'HMAC-SHA1',
                    'oauth_timestamp': str(int(time.time())),
                    'oauth_token': self.access_token,
                    'oauth_version': '1.0'
                }

                append_data = {
                    'command': 'APPEND',
                    'media_id': media_id,
                    'segment_index': '0'
                }
                
                # For APPEND, only use OAuth params in signature
                signature = generate_oauth_signature(
                    'POST',
                    UPLOAD_ENDPOINT,
                    oauth_params,
                    self.consumer_secret,
                    self.access_token_secret
                )
                oauth_params['oauth_signature'] = signature
                
                auth_header = 'OAuth ' + ', '.join(
                    f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                    for k, v in sorted(oauth_params.items())
                )

                # Format multipart data
                multipart_data = {}
                for key, value in append_data.items():
                    multipart_data[key] = (None, str(value))
                multipart_data['media'] = ('blob', chunk, mime_type)

                append_response = await self.client.post(
                    UPLOAD_ENDPOINT,
                    files=multipart_data,
                    headers={'Authorization': auth_header}
                )

                if append_response.status_code not in (200, 201, 202, 204):
                    logger.error(f"APPEND failed with status {append_response.status_code}: {append_response.text}")
                    continue

                logger.info("APPEND successful")

                # FINALIZE phase
                oauth_params = {
                    'oauth_consumer_key': self.consumer_key,
                    'oauth_nonce': generate_nonce(),
                    'oauth_signature_method': 'HMAC-SHA1',
                    'oauth_timestamp': str(int(time.time())),
                    'oauth_token': self.access_token,
                    'oauth_version': '1.0'
                }

                finalize_data = {
                    'command': 'FINALIZE',
                    'media_id': media_id
                }
                
                # Include all params in signature for FINALIZE
                all_params = {**oauth_params, **finalize_data}
                signature = generate_oauth_signature(
                    'POST',
                    UPLOAD_ENDPOINT,
                    all_params,
                    self.consumer_secret,
                    self.access_token_secret
                )
                oauth_params['oauth_signature'] = signature
                
                auth_header = 'OAuth ' + ', '.join(
                    f'{quote(k, safe="~")}="{quote(v, safe="~")}"'
                    for k, v in sorted(oauth_params.items())
                )

                finalize_response = await self.client.post(
                    UPLOAD_ENDPOINT,
                    data=finalize_data,
                    headers={
                        'Authorization': auth_header,
                        'Content-Type': 'application/x-www-form-urlencoded'
                    }
                )

                if finalize_response.status_code not in (200, 201, 202):
                    logger.error(f"FINALIZE failed with status {finalize_response.status_code}: {finalize_response.text}")
                    continue

                media_ids.append(media_id)
                logger.info(f"Successfully uploaded {media_path} as {media_id}")

            except Exception as e:
                logger.error(f"Error uploading {media_path}: {str(e)}")
                continue

        return media_ids

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



# import logging
# import asyncio
# from typing import Optional, Dict, List
# from datetime import datetime, timezone

# # twitter_client.py
# from .twitter.http_client import TwitterHttpClient
# from .twitter.auth import construct_proxy_url
# from .twitter.operations.tweets import TweetOperations
# from .twitter.operations.users import UserOperations
# from .twitter.operations.media import MediaOperations
# from .twitter.operations.direct_messages import DirectMessageOperations
# from .twitter.operations.trends import TrendOperations

# # Export construct_proxy_url for external use
# __all__ = ['TwitterClient', 'construct_proxy_url']

# logger = logging.getLogger(__name__)

# class TwitterClient:
#     def __init__(
#         self,
#         account_no: str,
#         auth_token: str,
#         ct0: str,
#         consumer_key: str = None,
#         consumer_secret: str = None,
#         bearer_token: str = None,
#         access_token: str = None,
#         access_token_secret: str = None,
#         client_id: str = None,
#         proxy_config: Optional[Dict[str, str]] = None,
#         user_agent: Optional[str] = None
#     ):
#         """Initialize TwitterClient with authentication and configuration"""
#         # Store account info
#         self.account_no = account_no
        
#         # Initialize HTTP client
#         self.http_client = TwitterHttpClient(
#             auth_token=auth_token,
#             ct0=ct0,
#             consumer_key=consumer_key,
#             consumer_secret=consumer_secret,
#             bearer_token=bearer_token,
#             access_token=access_token,
#             access_token_secret=access_token_secret,
#             proxy_config=proxy_config,
#             user_agent=user_agent
#         )
        
#         # Initialize operation handlers
#         self._tweet_ops = TweetOperations(self.http_client)
#         self._user_ops = UserOperations(self.http_client)
#         self._media_ops = MediaOperations(self.http_client)
#         self._dm_ops = DirectMessageOperations(self.http_client)
#         self._trend_ops = TrendOperations(self.http_client)

#     # Tweet Operations
#     async def get_user_tweets(
#         self,
#         username: str,
#         count: int = 40,
#         hours: Optional[int] = None,
#         max_replies: Optional[int] = None,
#         cursor: Optional[str] = None,
#         include_replies: bool = True
#     ) -> Dict:
#         """Get tweets from a user's timeline"""
#         return await self._tweet_ops.get_user_tweets(
#             username=username,
#             count=count,
#             hours=hours,
#             max_replies=max_replies,
#             cursor=cursor,
#             include_replies=include_replies
#         )

#     async def get_tweet_replies(
#         self,
#         tweet_id: str,
#         max_replies: int,
#         cursor: Optional[str] = None
#     ) -> Dict:
#         """Get replies to a specific tweet"""
#         return await self._tweet_ops.get_tweet_replies(
#             tweet_id=tweet_id,
#             max_replies=max_replies,
#             cursor=cursor
#         )

#     async def like_tweet(self, tweet_id: str) -> Dict:
#         """Like a tweet"""
#         return await self._tweet_ops.like_tweet(tweet_id)

#     async def unlike_tweet(self, tweet_id: str) -> Dict:
#         """Unlike a tweet"""
#         return await self._tweet_ops.unlike_tweet(tweet_id)

#     async def retweet(self, tweet_id: str) -> Dict:
#         """Retweet a tweet"""
#         return await self._tweet_ops.retweet(tweet_id)

#     async def quote_tweet(
#         self,
#         tweet_id: str,
#         text_content: str,
#         media: Optional[str] = None
#     ) -> Dict:
#         """Quote tweet with optional media"""
#         return await self._tweet_ops.quote_tweet(
#             tweet_id=tweet_id,
#             text_content=text_content,
#             media=media
#         )

#     async def reply_tweet(
#         self,
#         tweet_id: str,
#         text_content: str,
#         media: Optional[str] = None
#     ) -> Dict:
#         """Reply to a tweet with optional media"""
#         return await self._tweet_ops.reply_tweet(
#             tweet_id=tweet_id,
#             text_content=text_content,
#             media=media
#         )

#     # User Operations
#     async def get_user_id(self, username: str) -> str:
#         """Get user ID from username"""
#         return await self._user_ops.get_user_id(username)

#     async def follow_user(self, user: str) -> Dict:
#         """Follow a user by username or ID"""
#         return await self._user_ops.follow_user(user)

#     async def unfollow_user(self, user: str) -> Dict:
#         """Unfollow a user by username or ID"""
#         return await self._user_ops.unfollow_user(user)

#     async def update_profile(
#         self,
#         name: Optional[str] = None,
#         description: Optional[str] = None,
#         url: Optional[str] = None,
#         location: Optional[str] = None,
#         profile_image: Optional[str] = None,
#         profile_banner: Optional[str] = None,
#         lang: Optional[str] = None,
#         new_login: Optional[str] = None
#     ) -> Dict:
#         """Update user profile information"""
#         return await self._user_ops.update_profile(
#             name=name,
#             description=description,
#             url=url,
#             location=location,
#             profile_image=profile_image,
#             profile_banner=profile_banner,
#             lang=lang,
#             new_login=new_login
#         )

#     # Media Operations
#     async def upload_media(
#         self,
#         media_paths: List[str],
#         for_dm: bool = False
#     ) -> List[str]:
#         """Upload media files and return media IDs"""
#         return await self._media_ops.upload_media(
#             media_paths=media_paths,
#             for_dm=for_dm
#         )

#     # Direct Message Operations
#     async def send_dm(
#         self,
#         recipient_id: str,
#         text: str,
#         media: Optional[str] = None
#     ) -> Dict:
#         """Send a direct message with optional media"""
#         return await self._dm_ops.send_dm(
#             recipient_id=recipient_id,
#             text=text,
#             media=media
#         )

#     # Trend Operations
#     async def get_trending_topics(self) -> Dict:
#         """Get current trending topics"""
#         return await self._trend_ops.get_trending_topics()

#     async def get_topic_tweets(
#         self,
#         keyword: str,
#         count: int,
#         cursor: Optional[str] = None
#     ) -> Dict:
#         """Get tweets for a specific topic or keyword"""
#         return await self._trend_ops.get_topic_tweets(
#             keyword=keyword,
#             count=count,
#             cursor=cursor
#         )

#     async def search_users(
#         self,
#         keyword: str,
#         count: int,
#         cursor: Optional[str] = None
#     ) -> Dict:
#         """Search for users by keyword"""
#         return await self._trend_ops.search_users(
#             keyword=keyword,
#             count=count,
#             cursor=cursor
#         )

#     async def close(self):
#         """Close the client and cleanup resources"""
#         try:
#             await self.http_client.close()
#             logger.info(f"Successfully closed Twitter client for account {self.account_no}")
#         except Exception as e:
#             logger.error(f"Error closing Twitter client: {str(e)}")
#             raise

#     async def __aenter__(self):
#         """Async context manager entry"""
#         return self

#     async def __aexit__(self, exc_type, exc_val, exc_tb):
#         """Async context manager exit"""
#         await self.close()
