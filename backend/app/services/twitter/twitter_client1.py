import logging
from typing import Dict, List, Optional

from .twitter.base_client import BaseTwitterClient
from .twitter.media_client import MediaClient
from .twitter.tweet_client import TweetClient
from .twitter.user_client import UserClient
from .twitter.search_client import SearchClient
from .twitter.dm_client import DMClient
from .twitter.types import ProxyConfig
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

def construct_proxy_url(proxy_config: ProxyConfig) -> str:
    """Construct proxy URL from config"""
    if not proxy_config:
        return None
        
    # Extract components
    host = proxy_config.get('host')
    port = proxy_config.get('port')
    username = proxy_config.get('username')
    password = proxy_config.get('password')
    
    if not host or not port:
        return None
        
    # Construct auth string if credentials provided
    auth = ''
    if username and password:
        auth = f"{username}:{password}@"
        
    # Build URL
    return f"http://{auth}{host}:{port}"

class TwitterClient:
    """
    Main Twitter client that delegates operations to specialized clients.
    Each specialized client handles a specific aspect of the Twitter API.
    """
    
    def __init__(
        self,
        account_no: str,
        auth_token: str,
        ct0: str,
        consumer_key: Optional[str] = None,
        consumer_secret: Optional[str] = None,
        bearer_token: Optional[str] = None,
        access_token: Optional[str] = None,
        access_token_secret: Optional[str] = None,
        client_id: Optional[str] = None,
        proxy_config: Optional[ProxyConfig] = None,
        user_agent: Optional[str] = None
    ):
        """Initialize Twitter client with authentication and configuration"""
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
        self.user_agent = user_agent

        # Initialize specialized clients
        self._media_client = None
        self._tweet_client = None
        self._user_client = None
        self._search_client = None
        self._dm_client = None

    @property
    def media_client(self) -> MediaClient:
        """Get or create media client"""
        if not self._media_client:
            self._media_client = MediaClient(
                account_no=self.account_no,
                auth_token=self.auth_token,
                ct0=self.ct0,
                consumer_key=self.consumer_key,
                consumer_secret=self.consumer_secret,
                access_token=self.access_token,
                access_token_secret=self.access_token_secret,
                proxy_config=self.proxy_config,
                user_agent=self.user_agent
            )
        return self._media_client

    @property
    def tweet_client(self) -> TweetClient:
        """Get or create tweet client"""
        if not self._tweet_client:
            self._tweet_client = TweetClient(
                account_no=self.account_no,
                auth_token=self.auth_token,
                ct0=self.ct0,
                consumer_key=self.consumer_key,
                consumer_secret=self.consumer_secret,
                access_token=self.access_token,
                access_token_secret=self.access_token_secret,
                proxy_config=self.proxy_config,
                user_agent=self.user_agent
            )
        return self._tweet_client

    @property
    def user_client(self) -> UserClient:
        """Get or create user client"""
        if not self._user_client:
            self._user_client = UserClient(
                account_no=self.account_no,
                auth_token=self.auth_token,
                ct0=self.ct0,
                consumer_key=self.consumer_key,
                consumer_secret=self.consumer_secret,
                access_token=self.access_token,
                access_token_secret=self.access_token_secret,
                proxy_config=self.proxy_config,
                user_agent=self.user_agent
            )
        return self._user_client

    @property
    def search_client(self) -> SearchClient:
        """Get or create search client"""
        if not self._search_client:
            self._search_client = SearchClient(
                account_no=self.account_no,
                auth_token=self.auth_token,
                ct0=self.ct0,
                consumer_key=self.consumer_key,
                consumer_secret=self.consumer_secret,
                access_token=self.access_token,
                access_token_secret=self.access_token_secret,
                proxy_config=self.proxy_config,
                user_agent=self.user_agent
            )
        return self._search_client

    @property
    def dm_client(self) -> DMClient:
        """Get or create DM client"""
        if not self._dm_client:
            self._dm_client = DMClient(
                account_no=self.account_no,
                auth_token=self.auth_token,
                ct0=self.ct0,
                consumer_key=self.consumer_key,
                consumer_secret=self.consumer_secret,
                access_token=self.access_token,
                access_token_secret=self.access_token_secret,
                proxy_config=self.proxy_config,
                user_agent=self.user_agent
            )
        return self._dm_client

    # Media operations
    async def upload_media(self, media_paths: List[str], for_dm: bool = False) -> List[str]:
        """Upload media files"""
        return await self.media_client.upload_media(media_paths, for_dm)

    # Tweet operations
    async def get_user_tweets(
        self,
        username: str,
        count: int = 40,
        hours: Optional[int] = None,
        cursor: Optional[str] = None
    ) -> Dict:
        """Get user tweets"""
        return await self.tweet_client.get_user_tweets(
            username, count, hours, cursor
        )

    async def get_tweet_replies(
        self,
        tweet_id: str,
        max_replies: int,
        cursor: Optional[str] = None
    ) -> Dict:
        """Get replies for a tweet"""
        return await self.tweet_client.get_tweet_replies(tweet_id, max_replies, cursor)

    # User operations
    async def get_user_id(self, username: str) -> str:
        """Get user ID from username"""
        return await self.user_client.get_user_id(username)

    async def follow_user(self, user: str) -> Dict:
        """Follow a user"""
        return await self.user_client.follow_user(user)

    async def unfollow_user(self, target_user_id: str) -> Dict:
        """Unfollow a user"""
        return await self.user_client.unfollow_user(target_user_id)

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
        """Update user profile"""
        return await self.user_client.update_profile(
            name, description, url, location,
            profile_image, profile_banner, lang
        )

    # Search operations
    async def get_trending_topics(self) -> Dict:
        """Get trending topics"""
        return await self.search_client.get_trending_topics()

    async def get_topic_tweets(
        self,
        keyword: str,
        count: int = 20,
        cursor: Optional[str] = None
    ) -> Dict:
        """Search tweets by keyword"""
        return await self.search_client.get_topic_tweets(keyword, count, cursor)

    async def search_users(
        self,
        keyword: str,
        count: int = 20,
        cursor: Optional[str] = None
    ) -> Dict:
        """Search users"""
        return await self.search_client.search_users(keyword, count, cursor)

    # DM operations
    async def send_dm(
        self,
        recipient_id: str,
        text: str,
        media: Optional[str] = None
    ) -> Dict:
        """Send a direct message"""
        return await self.dm_client.send_dm(recipient_id, text, media)

    async def close(self):
        """Close all client connections"""
        clients = [
            self._media_client,
            self._tweet_client,
            self._user_client,
            self._search_client,
            self._dm_client
        ]
        for client in clients:
            if client:
                await client.close()
