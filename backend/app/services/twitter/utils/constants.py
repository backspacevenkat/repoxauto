"""
Constants used throughout the Twitter API client
"""

# Default HTTP headers
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'x-twitter-active-user': 'yes',
    'x-twitter-client-language': 'en',
    'content-type': 'application/json',
    'accept': '*/*',
    'Accept': '*/*',
    'accept-language': 'en-US,en;q=0.9',
    'accept-encoding': 'gzip, deflate, br'
}

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
    "responsive_web_enhance_cards_enabled": False,
    "responsive_web_media_download_video_enabled": True,
    "hidden_profile_subscriptions_enabled": True,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": False,
    "responsive_web_grok_share_attachment_enabled": True,
    "articles_preview_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True
}

# API URL Constants
API_URLS = {
    'upload': 'https://upload.twitter.com/1.1/media/upload.json',
    'graphql_base': 'https://twitter.com/i/api/graphql',
    'api_v1_base': 'https://api.twitter.com/1.1',
    'api_v2_base': 'https://api.twitter.com/2'
}

# Media Categories
MEDIA_CATEGORIES = {
    'tweet_image': ['image/jpeg', 'image/png'],
    'tweet_gif': ['image/gif'],
    'tweet_video': ['video/mp4', 'video/quicktime'],
    'dm_image': ['image/jpeg', 'image/png'],
    'dm_gif': ['image/gif'],
    'dm_video': ['video/mp4', 'video/quicktime']
}

# Rate Limits
RATE_LIMITS = {
    'tweets': {
        'get_user_tweets': 900,  # requests per 15 minutes
        'like_tweet': 50,
        'retweet': 25,
        'create_tweet': 200,
        'delete_tweet': 100
    },
    'users': {
        'get_user_info': 900,
        'follow_user': 400,
        'unfollow_user': 400,
        'update_profile': 50
    },
    'direct_messages': {
        'send_dm': 1000,
        'get_conversations': 900
    },
    'media': {
        'upload': 500
    }
}

# Error Messages
ERROR_MESSAGES = {
    'rate_limit': 'Rate limit exceeded. Please try again later.',
    'auth_error': 'Authentication failed. Please check your credentials.',
    'media_error': 'Error uploading media. Please try again.',
    'network_error': 'Network error occurred. Please check your connection.',
    'invalid_request': 'Invalid request parameters.',
    'not_found': 'Resource not found.',
    'server_error': 'Twitter server error occurred.'
}

# HTTP Status Codes
HTTP_STATUS = {
    'OK': 200,
    'CREATED': 201,
    'ACCEPTED': 202,
    'NO_CONTENT': 204,
    'BAD_REQUEST': 400,
    'UNAUTHORIZED': 401,
    'FORBIDDEN': 403,
    'NOT_FOUND': 404,
    'RATE_LIMIT': 429,
    'SERVER_ERROR': 500
}

# Timeouts (in seconds)
TIMEOUTS = {
    'connect': 20,
    'read': 40,
    'write': 40,
    'pool': 40,
    'media_upload': 300
}

# Retries
RETRY_CONFIG = {
    'max_retries': 3,
    'base_delay': 1,
    'max_delay': 60,
    'exponential_base': 2
}