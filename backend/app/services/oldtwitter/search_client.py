import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

from .base_client import BaseTwitterClient
from .types import (
    SearchResponse, TrendingResponse,
    GRAPHQL_ENDPOINTS, DEFAULT_FEATURES,
    API_ENDPOINTS
)

logger = logging.getLogger(__name__)

class SearchClient(BaseTwitterClient):
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
                "withV2Timeline": True
            }

            features = DEFAULT_FEATURES.copy()
            features.update({
                "responsive_web_graphql_timeline_navigation_enabled": True,
                "responsive_web_twitter_article_tweet_consumption_enabled": True,
                "longform_notetweets_consumption_enabled": True
            })

            response = await self.graphql_request(
                'SearchTimeline',
                variables,
                features
            )

            if not response or 'data' not in response:
                raise Exception("Failed to get trending topics")

            # Extract trends from response
            trends = []
            timeline = response.get('data', {}).get('search_by_raw_query', {}).get('search_timeline', {})
            
            if not timeline:
                return {
                    "success": True,
                    "trends": [],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "location": "Worldwide"
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
                                    "location": "Worldwide",
                                    "as_of": datetime.now(timezone.utc).isoformat()
                                })

            # Sort trends by tweet volume
            trends.sort(key=lambda x: x.get('tweet_volume', 0) or 0, reverse=True)

            return {
                "success": True,
                "trends": trends,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "location": "Worldwide"
            }

        except Exception as e:
            logger.error(f"Error getting trending topics: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_topic_tweets(
        self,
        keyword: str,
        count: int = 20,
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
                "product": "Top"
            }

            features = DEFAULT_FEATURES.copy()
            features.update({
                "responsive_web_twitter_blue_verified_badge_is_enabled": True,
                "responsive_web_graphql_exclude_directive_enabled": True,
                "verified_phone_label_enabled": False,
                "responsive_web_graphql_timeline_navigation_enabled": True,
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False
            })

            response = await self.graphql_request(
                'SearchTimeline',
                variables,
                features
            )

            if not response or 'data' not in response:
                raise Exception("Failed to search tweets")

            # Extract tweets from response
            tweets = []
            next_cursor = None

            timeline_data = response.get('data', {}).get('search_by_raw_query', {}).get('search_timeline', {}).get('timeline', {})
            if not timeline_data:
                raise Exception("No timeline data found")

            for instruction in timeline_data.get('instructions', []):
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
                                # Process tweet data directly
                                tweet_data = tweet_results.get('legacy', {})
                                if tweet_data:
                                    tweet = {
                                        'id': tweet_results.get('rest_id'),
                                        'tweet_url': f"https://twitter.com/{tweet_data.get('user', {}).get('screen_name')}/status/{tweet_data.get('id_str')}",
                                        'created_at': tweet_data.get('created_at'),
                                        'text': tweet_data.get('full_text') or tweet_data.get('text', ''),
                                        'author': tweet_data.get('user', {}).get('screen_name'),
                                        'metrics': {
                                            'retweet_count': tweet_data.get('retweet_count', 0),
                                            'reply_count': tweet_data.get('reply_count', 0),
                                            'like_count': tweet_data.get('favorite_count', 0),
                                            'quote_count': tweet_data.get('quote_count', 0),
                                            'view_count': tweet_results.get('views', {}).get('count', 0),
                                            'bookmark_count': tweet_data.get('bookmark_count', 0)
                                        }
                                    }
                                    tweets.append(tweet)

            # Sort tweets by time (newest first)
            tweets.sort(key=lambda x: datetime.strptime(x['created_at'], '%a %b %d %H:%M:%S %z %Y'), reverse=True)

            return {
                'success': True,
                'tweets': tweets[:count],
                'next_cursor': next_cursor if len(tweets) >= count else None,
                'keyword': keyword,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error searching tweets: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    async def search_users(
        self,
        keyword: str,
        count: int = 20,
        cursor: Optional[str] = None
    ) -> Dict:
        """Search users by keyword"""
        logger.info(f"Searching users for keyword: {keyword}")
        try:
            variables = {
                "searchMode": "People",
                "rawQuery": keyword,
                "count": count * 2,
                "cursor": cursor,
                "querySource": "typed_query",
                "product": "People"
            }

            features = DEFAULT_FEATURES.copy()
            features.update({
                "responsive_web_twitter_blue_verified_badge_is_enabled": True,
                "responsive_web_graphql_exclude_directive_enabled": True,
                "verified_phone_label_enabled": False,
                "responsive_web_graphql_timeline_navigation_enabled": True,
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False
            })

            response = await self.graphql_request(
                'SearchTimeline',
                variables,
                features
            )

            if not response or 'data' not in response:
                raise Exception("Failed to search users")

            # Extract users from response
            users = []
            next_cursor = None

            timeline_data = response.get('data', {}).get('search_by_raw_query', {}).get('search_timeline', {}).get('timeline', {})
            if not timeline_data:
                raise Exception("No timeline data found")

            for instruction in timeline_data.get('instructions', []):
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
                'success': True,
                'users': users[:count],
                'next_cursor': next_cursor if len(users) >= count else None,
                'keyword': keyword,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error searching users: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
