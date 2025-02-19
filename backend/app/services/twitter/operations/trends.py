import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone
import asyncio
import random

logger = logging.getLogger(__name__)

class TrendOperations:
    def __init__(self, http_client):
        """Initialize TrendOperations with HTTP client"""
        self.http_client = http_client

    async def get_trending_topics(self) -> Dict:
        """Get current trending topics"""
        logger.info("Fetching trending topics")
        try:
            variables = {
                "rawQuery": "trending",
                "count": 40,
                "querySource": "explore_trending",
                "product": "Top",
                "withDownvotePerspective": False,
                "withReactionsMetadata": False,
                "withReactionsPerspective": False
            }

            response = await self.http_client.graphql_request('SearchTimeline', variables)
            
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
                                    "location": "Worldwide",
                                    "as_of": datetime.now(timezone.utc).isoformat()
                                })

            # Sort trends by tweet volume
            trends.sort(key=lambda x: x.get('tweet_volume', 0) or 0, reverse=True)

            # Analyze trends
            analysis = await self._analyze_trends(trends)

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

    async def _analyze_trends(self, trends: List[Dict]) -> Dict:
        """Analyze trend data and generate statistics"""
        try:
            analysis = {
                "total_volume": 0,
                "max_volume": 0,
                "min_volume": float('inf'),
                "top_trends": []
            }

            for trend in trends:
                volume = trend.get("tweet_volume", 0) or 0
                analysis["total_volume"] += volume
                analysis["max_volume"] = max(analysis["max_volume"], volume)
                if volume > 0:
                    analysis["min_volume"] = min(analysis["min_volume"], volume)

            if not trends:
                analysis["min_volume"] = 0
            elif analysis["min_volume"] == float('inf'):
                analysis["min_volume"] = 0

            analysis["top_trends"] = sorted(
                [t for t in trends if t.get("tweet_volume", 0)],
                key=lambda x: x.get("tweet_volume", 0) or 0,
                reverse=True
            )[:10]

            return analysis

        except Exception as e:
            logger.error(f"Error analyzing trends: {str(e)}")
            return {
                "total_volume": 0,
                "max_volume": 0,
                "min_volume": 0,
                "top_trends": []
            }

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
                "product": "Top"
            }

            response = await self.http_client.graphql_request('SearchTimeline', variables)

            if not response or 'data' not in response:
                raise Exception("Failed to search tweets")

            tweets = []
            next_cursor = None

            # Extract tweets from response
            timeline_data = response.get('data', {}).get('search_by_raw_query', {}).get('search_timeline', {}).get('timeline', {})

            for instruction in timeline_data.get('instructions', []):
                if instruction.get('type') == 'TimelineAddEntries':
                    for entry in instruction.get('entries', []):
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
            tweets.sort(
                key=lambda x: datetime.strptime(x['created_at'], '%a %b %d %H:%M:%S %z %Y'),
                reverse=True
            )

            return {
                'tweets': tweets[:count],
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
                "count": count * 2,
                "cursor": cursor,
                "querySource": "typed_query",
                "product": "People"
            }

            response = await self.http_client.graphql_request('SearchTimeline', variables)

            if not response or 'data' not in response:
                raise Exception("Failed to search users")

            users = []
            next_cursor = None

            timeline_data = response.get('data', {}).get('search_by_raw_query', {}).get('search_timeline', {}).get('timeline', {})

            for instruction in timeline_data.get('instructions', []):
                if instruction.get('type') == 'TimelineAddEntries':
                    for entry in instruction.get('entries', []):
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
                'users': users[:count],
                'next_cursor': next_cursor if len(users) >= count else None,
                'keyword': keyword,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error searching users: {str(e)}")
            raise

    async def _process_tweet_data(self, tweet_data: Dict) -> Optional[Dict]:
        """Process raw tweet data into normalized format"""
        try:
            if not tweet_data:
                return None

            legacy = tweet_data.get('legacy', {})
            user_results = tweet_data.get('core', {}).get('user_results', {}).get('result', {})
            
            if not legacy or not user_results:
                return None

            return {
                'id': tweet_data.get('rest_id'),
                'text': legacy.get('full_text'),
                'created_at': legacy.get('created_at'),
                'author': user_results.get('legacy', {}).get('screen_name'),
                'metrics': {
                    'retweet_count': legacy.get('retweet_count', 0),
                    'reply_count': legacy.get('reply_count', 0),
                    'like_count': legacy.get('favorite_count', 0),
                    'quote_count': legacy.get('quote_count', 0)
                },
                'urls': [url.get('expanded_url') for url in legacy.get('entities', {}).get('urls', [])],
                'media': [media.get('media_url_https') for media in legacy.get('entities', {}).get('media', [])],
                'hashtags': [tag.get('text') for tag in legacy.get('entities', {}).get('hashtags', [])],
                'mentions': [mention.get('screen_name') for mention in legacy.get('entities', {}).get('user_mentions', [])]
            }

        except Exception as e:
            logger.error(f"Error processing tweet data: {str(e)}")
            return None