import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta

from .base_client import BaseTwitterClient
from .user_client import UserClient
from .types import (
    Tweet, TweetResponse, GRAPHQL_ENDPOINTS,
    DEFAULT_FEATURES, API_ENDPOINTS
)

logger = logging.getLogger(__name__)

class TweetClient(BaseTwitterClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_client = UserClient(*args, **kwargs)
    async def get_user_tweets(
        self,
        username: str,
        count: int = 40,
        hours: Optional[int] = None,
        cursor: Optional[str] = None
    ) -> Dict:
        """Get user tweets using GraphQL"""
        logger.info(f"Getting tweets for user {username}")
        try:
            # Get user ID using UserClient
            user_id = await self.user_client.get_user_id(username)
            if not user_id:
                raise Exception(f"Could not get user ID for {username}")
            logger.info(f"Found user ID {user_id} for {username}")

            variables = {
                "userId": user_id,
                "count": count,
                "cursor": cursor,
                "includePromotedContent": False,
                "withQuickPromoteEligibilityTweetFields": True,
                "withVoice": True,
                "withV2Timeline": True
            }

            # Add all the necessary features for rich tweet data
            features = DEFAULT_FEATURES.copy()
            features.update({
                "rweb_video_timestamps_enabled": True,
                "responsive_web_graphql_timeline_navigation_enabled": True,
                "responsive_web_twitter_article_tweet_consumption_enabled": True,
                "longform_notetweets_consumption_enabled": True,
                "responsive_web_media_download_video_enabled": True
            })

            response = await self._make_request(
                method="GET",
                url=f"{API_ENDPOINTS['graphql']}/{GRAPHQL_ENDPOINTS['UserTweets']}/UserTweets",
                params={
                    "variables": variables,
                    "features": features
                },
                headers=self.graphql_headers
            )

            if not response or 'data' not in response:
                raise Exception("Failed to get user tweets")

            # Extract tweets from response
            tweets = []
            next_cursor = None

            timeline_data = response.get('data', {}).get('user', {}).get('result', {}).get('timeline_v2', {}).get('timeline', {})
            if not timeline_data:
                raise Exception("No timeline data found")

            instructions = timeline_data.get('instructions', [])
            if not instructions:
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

            return {
                'tweets': tweets[:count],
                'next_cursor': next_cursor if len(tweets) >= count else None,
                'username': username,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error getting tweets for user {username}: {str(e)}")
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
                "includePromotedContent": False
            }

            features = DEFAULT_FEATURES.copy()
            features.update({
                "responsive_web_twitter_blue_verified_badge_is_enabled": True,
                "responsive_web_graphql_exclude_directive_enabled": True,
                "verified_phone_label_enabled": False,
                "responsive_web_graphql_timeline_navigation_enabled": True,
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False
            })

            response = await self._make_request(
                method="GET",
                url=f"{API_ENDPOINTS['graphql']}/{GRAPHQL_ENDPOINTS['TweetDetail']}/TweetDetail",
                params={
                    "variables": variables,
                    "features": features
                },
                headers=self.graphql_headers
            )

            if 'errors' in response:
                logger.error(f"Error in tweet detail response: {response['errors']}")
                return {'replies': [], 'next_cursor': None}

            entries = response.get('data', {}).get('threaded_conversation_with_injections_v2', {}).get('instructions', [])
            if not entries:
                return {'replies': [], 'next_cursor': None}

            # Process entries to get all tweets
            all_tweets = []
            next_cursor = None
            original_tweet = None

            for instruction in entries:
                if instruction.get('type') == 'TimelineAddEntries':
                    for entry in instruction.get('entries', []):
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
                return {'replies': [], 'next_cursor': None}

            # Sort tweets by time
            all_tweets.sort(key=lambda x: datetime.strptime(x['created_at'], '%a %b %d %H:%M:%S %z %Y'))

            # Organize replies and threads
            replies = []
            current_thread = []
            original_author = original_tweet['author']

            for tweet in all_tweets:
                is_reply_to_original = tweet.get('reply_to_status_id') == tweet_id
                is_thread = tweet['author'] == original_author
                is_consecutive_reply = False

                if current_thread and is_thread:
                    last_thread_tweet = current_thread[-1]
                    is_consecutive_reply = (
                        tweet.get('reply_to_status_id') == last_thread_tweet['id'] or
                        tweet.get('conversation_id') == tweet_id or
                        (tweet.get('reply_to_screen_name') == original_author and
                        abs(datetime.strptime(tweet['created_at'], '%a %b %d %H:%M:%S %z %Y').timestamp() -
                        datetime.strptime(last_thread_tweet['created_at'], '%a %b %d %H:%M:%S %z %Y').timestamp()) < 300)
                    )

                if is_consecutive_reply:
                    current_thread.append(tweet)
                    continue

                if current_thread:
                    replies.append({
                        'type': 'thread',
                        'tweets': current_thread.copy()
                    })
                    current_thread = []

                if is_thread and is_reply_to_original:
                    current_thread.append(tweet)
                elif is_reply_to_original:
                    replies.append({
                        'type': 'reply',
                        'tweet': tweet
                    })

                if len(replies) >= max_replies:
                    break

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

            # Handle retweets
            if 'retweeted_status_result' in tweet_data.get('legacy', {}):
                retweet_data = tweet_data['legacy']['retweeted_status_result']['result']
                processed = await self._process_tweet_data(retweet_data)
                if processed:
                    processed['retweeted_by'] = tweet_data.get('core', {}).get('user_results', {}).get('result', {}).get('legacy', {}).get('screen_name')
                    processed['retweeted_at'] = tweet_data.get('legacy', {}).get('created_at')
                    return processed

            # Get tweet result data
            result = (
                tweet_data.get('tweet_results', {}).get('result', {}) or
                tweet_data.get('itemContent', {}).get('tweet_results', {}).get('result', {}) or
                tweet_data.get('content', {}).get('itemContent', {}).get('tweet_results', {}).get('result', {}) or
                tweet_data.get('tweet', {}) or
                tweet_data
            )
            
            if not result:
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
            
            # Get author info
            author = None
            user_data = (
                result.get('core', {}).get('user_results', {}).get('result', {}) or
                result.get('user_results', {}).get('result', {}) or
                result.get('user', {}) or
                legacy.get('user', {})
            )
            
            if user_data:
                author = (
                    user_data.get('legacy', {}).get('screen_name') or
                    user_data.get('screen_name')
                )
            
            if not author or not legacy:
                return None

            # Get tweet ID and build URL
            tweet_id = str(tweet_data.get('rest_id') or legacy.get('id_str'))
            if not tweet_id:
                return None

            tweet_url = f"https://twitter.com/{author}/status/{tweet_id}"

            # Extract tweet text
            text = (
                legacy.get('full_text') or
                tweet_data.get('text') or
                legacy.get('text') or
                tweet_data.get('legacy', {}).get('full_text')
            )

            if not text:
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

    async def close(self):
        """Close all client connections"""
        try:
            await super().close()
            if self.user_client:
                await self.user_client.close()
        except Exception as e:
            logger.error(f"Error closing tweet client: {str(e)}")
