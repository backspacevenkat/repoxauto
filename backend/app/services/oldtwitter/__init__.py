"""
Twitter API client modules providing specialized functionality for different aspects
of the Twitter/X platform API.
"""

from .types import (
    ProxyConfig,
    Tweet,
    TweetMetrics,
    MediaItem,
    UrlItem,
    User,
    UserMetrics,
    ApiResponse,
    TweetResponse,
    UserResponse,
    SearchResponse,
    TrendingResponse
)

from .base_client import BaseTwitterClient
from .media_client import MediaClient
from .tweet_client import TweetClient
from .user_client import UserClient
from .search_client import SearchClient
from .dm_client import DMClient

__all__ = [
    # Types
    'ProxyConfig',
    'Tweet',
    'TweetMetrics',
    'MediaItem',
    'UrlItem',
    'User',
    'UserMetrics',
    'ApiResponse',
    'TweetResponse',
    'UserResponse',
    'SearchResponse',
    'TrendingResponse',
    
    # Clients
    'BaseTwitterClient',
    'MediaClient',
    'TweetClient',
    'UserClient',
    'SearchClient',
    'DMClient'
]

__version__ = '1.0.0'
