from typing import Dict, Optional, TypedDict, List, Union
from datetime import datetime

class ProxyConfig(TypedDict, total=False):
    proxy_username: str
    proxy_password: str
    proxy_url: str
    proxy_port: str

class TweetMetrics(TypedDict):
    retweet_count: int
    reply_count: int
    like_count: int
    quote_count: int
    view_count: int
    bookmark_count: int

class MediaItem(TypedDict):
    type: str
    url: str
    alt_text: Optional[str]
    video_url: Optional[str]
    duration_ms: Optional[int]

class UrlItem(TypedDict):
    url: str
    display_url: str
    title: Optional[str]
    description: Optional[str]
    unwound_url: Optional[str]

class Tweet(TypedDict):
    id: str
    tweet_url: str
    created_at: str
    text: str
    lang: Optional[str]
    source: Optional[str]
    conversation_id: Optional[str]
    reply_settings: Optional[str]
    metrics: TweetMetrics
    author: str
    is_reply: bool
    reply_to: Optional[str]
    reply_to_status_id: Optional[str]
    media: Optional[List[MediaItem]]
    urls: Optional[List[UrlItem]]
    quoted_tweet: Optional['Tweet']
    retweeted_by: Optional[str]
    retweeted_at: Optional[str]

class UserMetrics(TypedDict):
    followers_count: int
    following_count: int
    tweets_count: int
    likes_count: int
    media_count: Optional[int]

class User(TypedDict):
    id: str
    screen_name: str
    name: str
    description: Optional[str]
    location: Optional[str]
    url: Optional[str]
    profile_image_url: Optional[str]
    profile_banner_url: Optional[str]
    metrics: UserMetrics
    verified: bool
    protected: bool
    created_at: str
    professional: Optional[Dict]
    verified_type: Optional[str]

# GraphQL endpoint IDs
GRAPHQL_ENDPOINTS = {
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

# Default GraphQL features
DEFAULT_FEATURES = {
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
    "responsive_web_enhance_cards_enabled": False
}

# API endpoints
API_ENDPOINTS = {
    'upload': 'https://upload.twitter.com/1.1/media/upload.json',
    'dm_new': 'https://twitter.com/i/api/1.1/dm/new.json',
    'dm_lookup': 'https://twitter.com/i/api/1.1/dm/lookup.json',
    'graphql': 'https://twitter.com/i/api/graphql',
    'profile_update': 'https://api.twitter.com/1.1/account/update_profile.json',
    'profile_image': 'https://api.twitter.com/1.1/account/update_profile_image.json',
    'profile_banner': 'https://api.twitter.com/1.1/account/update_profile_banner.json',
    'settings': 'https://api.twitter.com/1.1/account/settings.json'
}

# Response types
class ApiResponse(TypedDict):
    success: bool
    error: Optional[str]
    rate_limited: Optional[bool]
    retry_after: Optional[int]

class TweetResponse(ApiResponse):
    tweet_id: Optional[str]
    text: Optional[str]
    type: Optional[str]
    timestamp: Optional[str]

class UserResponse(ApiResponse):
    user_id: Optional[str]
    screen_name: Optional[str]
    action: Optional[str]
    timestamp: Optional[str]

class SearchResponse(ApiResponse):
    tweets: Optional[List[Tweet]]
    users: Optional[List[User]]
    next_cursor: Optional[str]
    keyword: str
    timestamp: str

class TrendingResponse(ApiResponse):
    trends: List[Dict[str, Union[str, int]]]
    timestamp: str
    location: str
