import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

class TweetOperations:
    def __init__(self, http_client):
        """Initialize TweetOperations with HTTP client"""
        self.http_client = http_client

    async def get_user_tweets(
        self,
        username: str,
        count: int = 40,
        hours: Optional[int] = None,
        max_replies: Optional[int] = None,
        cursor: Optional[str] = None,
        include_replies: bool = True
    ) -> Dict:
        """Get tweets from a user's timeline"""
        logger.info(f"Getting tweets for user {username}")
        try:
            # First get user ID from username
            try:
                user_id = await self.http_client.graphql_request(
                    'UserByScreenName',
                    {'screen_name': username}
                )
                if not user_id:
                    raise Exception(f"Could not get user ID for {username}")
            except Exception as e:
                logger.error(f"Error getting user ID for {username}: {str(e)}")
                return {
                    'tweets': [],
                    'next_cursor': None,
                    'username': username,
                    'error': str(e)
                }

            variables = {
                "userId": user_id,
                "count": count,
                "cursor": cursor,
                "includePromotedContent": False,
                "withQuickPromoteEligibilityTweetFields": True,
                "withVoice": True,
                "withV2Timeline": True
            }

            endpoint = 'UserTweets' if not include_replies else 'UserTweetsAndReplies'
            response = await self.http_client.graphql_request(endpoint, variables)

            if not response or 'data' not in response:
                raise Exception("Failed to get user tweets")

            tweets = []
            next_cursor = None

            # Extract tweets from response
            timeline_data = response.get('data', {}).get('user', {}).get('result', {}).get('timeline_v2', {}).get('timeline', {})
            
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
            logger.error(f"Error getting tweets for {username}: {str(e)}")
            raise

    async def get_tweet_replies(
        self,
        tweet_id: str,
        max_replies: int,
        cursor: Optional[str] = None
    ) -> Dict:
        """Get replies for a tweet"""
        logger.info(f"Getting replies for tweet {tweet_id}")
        try:
            variables = {
                "focalTweetId": tweet_id,
                "cursor": cursor,
                "count": max_replies * 2,  # Request more to account for filtering
                "includePromotedContent": False
            }

            response = await self.http_client.graphql_request('TweetDetail', variables)

            entries = []
            next_cursor = None
            original_tweet = None
            all_tweets = []

            timeline_data = response.get('data', {}).get('threaded_conversation_with_injections_v2', {})

            for instruction in timeline_data.get('instructions', []):
                if instruction.get('type') == 'TimelineAddEntries':
                    entries.extend(instruction.get('entries', []))

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
                            if processed_tweet['id'] == tweet_id:
                                original_tweet = processed_tweet
                            else:
                                all_tweets.append(processed_tweet)

            if not original_tweet:
                return {'replies': [], 'next_cursor': None}

            # Organize replies
            replies = []
            current_thread = []
            original_author = original_tweet['author']

            for tweet in all_tweets:
                # Check if reply to original or thread
                is_reply_to_original = tweet.get('reply_to_status_id') == tweet_id
                is_thread = tweet['author'] == original_author
                
                if is_thread and is_reply_to_original:
                    current_thread.append(tweet)
                elif is_reply_to_original:
                    replies.append({
                        'type': 'reply',
                        'tweet': tweet
                    })

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

    async def like_tweet(self, tweet_id: str) -> Dict:
        """Like a tweet"""
        logger.info(f"Liking tweet {tweet_id}")
        try:
            variables = {
                "tweet_id": tweet_id
            }

            response = await self.http_client.graphql_request('FavoriteTweet', variables)

            if response and response.get('data', {}).get('favorite_tweet') == 'Done':
                return {
                    "success": True,
                    "tweet_id": tweet_id,
                    "action": "like",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

            return {
                "success": False,
                "error": "Failed to like tweet"
            }

        except Exception as e:
            logger.error(f"Error liking tweet {tweet_id}: {str(e)}")
            raise

    async def unlike_tweet(self, tweet_id: str) -> Dict:
        """Unlike a tweet"""
        logger.info(f"Unliking tweet {tweet_id}")
        try:
            variables = {
                "tweet_id": tweet_id
            }

            response = await self.http_client.graphql_request('UnfavoriteTweet', variables)

            if response and response.get('data', {}).get('unfavorite_tweet') == 'Done':
                return {
                    "success": True,
                    "tweet_id": tweet_id,
                    "action": "unlike",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

            return {
                "success": False,
                "error": "Failed to unlike tweet"
            }

        except Exception as e:
            logger.error(f"Error unliking tweet {tweet_id}: {str(e)}")
            raise

    async def retweet(self, tweet_id: str) -> Dict:
        """Retweet a tweet"""
        logger.info(f"Retweeting tweet {tweet_id}")
        try:
            variables = {
                "tweet_id": tweet_id
            }

            response = await self.http_client.graphql_request('CreateRetweet', variables)

            if response and response.get('data', {}).get('create_retweet'):
                return {
                    "success": True,
                    "tweet_id": tweet_id,
                    "action": "retweet",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

            return {
                "success": False,
                "error": "Failed to retweet"
            }

        except Exception as e:
            logger.error(f"Error retweeting {tweet_id}: {str(e)}")
            raise

    async def quote_tweet(
        self,
        tweet_id: str,
        text_content: str,
        media: Optional[str] = None
    ) -> Dict:
        """Quote tweet with optional media"""
        logger.info(f"Quote tweeting {tweet_id} with text '{text_content}'")
        try:
            # Handle media upload if provided
            media_ids = []
            if media:
                media_ids = await self.http_client.upload_media([media])

            variables = {
                "tweet_id": tweet_id,
                "text": text_content
            }

            if media_ids:
                variables["media"] = {"media_ids": media_ids}

            response = await self.http_client.graphql_request('CreateTweet', variables)

            if response and response.get('data', {}).get('create_tweet'):
                return {
                    "success": True,
                    "tweet_id": response['data']['create_tweet']['tweet_id'],
                    "text": text_content,
                    "type": "quote_tweet",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

            return {
                "success": False,
                "error": "Failed to create quote tweet"
            }

        except Exception as e:
            logger.error(f"Error quote tweeting {tweet_id}: {str(e)}")
            raise

    async def reply_tweet(
        self,
        tweet_id: str,
        text_content: str,
        media: Optional[str] = None
    ) -> Dict:
        """Reply to a tweet with optional media"""
        logger.info(f"Replying to tweet {tweet_id}")
        try:
            # Handle media upload if provided
            media_ids = []
            if media:
                media_ids = await self.http_client.upload_media([media])

            variables = {
                "tweet_id": tweet_id,
                "text": text_content,
                "reply": {
                    "in_reply_to_tweet_id": tweet_id
                }
            }

            if media_ids:
                variables["media"] = {"media_ids": media_ids}

            response = await self.http_client.graphql_request('CreateTweet', variables)

            if response and response.get('data', {}).get('create_tweet'):
                return {
                    "success": True,
                    "tweet_id": response['data']['create_tweet']['tweet_id'],
                    "text": text_content,
                    "type": "reply",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

            return {
                "success": False,
                "error": "Failed to create reply"
            }

        except Exception as e:
            logger.error(f"Error replying to tweet {tweet_id}: {str(e)}")
            raise

    async def _process_tweet_data(self, tweet_data: Dict) -> Optional[Dict]:
        """Process raw tweet data into normalized format"""
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

            legacy = tweet_data.get('legacy', {})
            user_data = tweet_data.get('core', {}).get('user_results', {}).get('result', {})
            author = user_data.get('legacy', {}).get('screen_name')

            if not legacy or not author:
                return None

            tweet_id = str(tweet_data.get('rest_id') or legacy.get('id_str'))
            if not tweet_id:
                return None

            processed = {
                'id': tweet_id,
                'tweet_url': f"https://twitter.com/{author}/status/{tweet_id}",
                'created_at': legacy.get('created_at'),
                'text': legacy.get('full_text') or legacy.get('text', ''),
                'lang': legacy.get('lang'),
                'source': legacy.get('source'),
                'metrics': {
                    'retweet_count': legacy.get('retweet_count', 0),
                    'reply_count': legacy.get('reply_count', 0),
                    'like_count': legacy.get('favorite_count', 0),
                    'quote_count': legacy.get('quote_count', 0),
                    'bookmark_count': legacy.get('bookmark_count', 0)
                },
                'author': author,
                'is_reply': bool(legacy.get('in_reply_to_status_id_str')),
                'reply_to': legacy.get('in_reply_to_screen_name'),
                'reply_to_status_id': legacy.get('in_reply_to_status_id_str')
            }

            # Handle media
            if 'extended_entities' in legacy:
                media_list = []
                for media in legacy['extended_entities'].get('media', []):
                    media_item = {
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
                                media_item['video_url'] = highest_bitrate['url']
                                media_item['duration_ms'] = media.get('video_info', {}).get('duration_millis')

                    media_list.append(media_item)
                processed['media'] = media_list

            # Handle quoted tweets
            if legacy.get('is_quote_status') and 'quoted_status_result' in tweet_data:
                quoted_data = tweet_data['quoted_status_result']['result']
                quoted_tweet = await self._process_tweet_data(quoted_data)
                if quoted_tweet:
                    processed['quoted_tweet'] = quoted_tweet

            # Handle URLs
            if 'entities' in legacy:
                urls = []
                for url in legacy['entities'].get('urls', []):
                    urls.append({
                        'url': url.get('expanded_url'),
                        'display_url': url.get('display_url'),
                        'title': url.get('title'),
                        'description': url.get('description'),
                        'unwound_url': url.get('unwound_url')
                    })
                processed['urls'] = urls

            # Process user mentions
            if 'entities' in legacy and 'user_mentions' in legacy['entities']:
                processed['mentions'] = [
                    {
                        'screen_name': mention.get('screen_name'),
                        'name': mention.get('name'),
                        'id': mention.get('id_str')
                    }
                    for mention in legacy['entities']['user_mentions']
                ]

            # Process hashtags
            if 'entities' in legacy and 'hashtags' in legacy['entities']:
                processed['hashtags'] = [
                    hashtag.get('text') for hashtag in legacy['entities']['hashtags']
                ]

            # Add conversation ID if available
            if 'conversation_id_str' in legacy:
                processed['conversation_id'] = legacy['conversation_id_str']

            # Add any available coordinates/place information
            if 'coordinates' in legacy:
                processed['coordinates'] = legacy['coordinates']
            if 'place' in legacy:
                processed['place'] = legacy['place']

            # Add tweet context annotations if available
            context_annotations = tweet_data.get('context_annotations', [])
            if context_annotations:
                processed['context_annotations'] = context_annotations

            return processed

        except Exception as e:
            logger.error(f"Error processing tweet data: {str(e)}")
            return None

    async def delete_tweet(self, tweet_id: str) -> Dict:
        """Delete a tweet"""
        logger.info(f"Deleting tweet {tweet_id}")
        try:
            variables = {
                "tweet_id": tweet_id,
                "dark_request": False
            }

            response = await self.http_client.graphql_request('DeleteTweet', variables)

            if response and response.get('data', {}).get('delete_tweet'):
                return {
                    "success": True,
                    "tweet_id": tweet_id,
                    "action": "delete",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

            return {
                "success": False,
                "error": "Failed to delete tweet"
            }

        except Exception as e:
            logger.error(f"Error deleting tweet {tweet_id}: {str(e)}")
            raise

    async def create_thread(
        self,
        tweets: List[str],
        media: Optional[List[str]] = None
    ) -> Dict:
        """Create a thread of tweets with optional media"""
        logger.info(f"Creating thread with {len(tweets)} tweets")
        try:
            thread_tweets = []
            reply_to = None
            media_ids = []

            # Handle media upload if provided
            if media:
                media_ids = await self.http_client.upload_media(media)

            for i, tweet_text in enumerate(tweets):
                variables = {
                    "text": tweet_text
                }

                # Add reply parameters if not first tweet
                if reply_to:
                    variables["reply"] = {
                        "in_reply_to_tweet_id": reply_to
                    }

                # Add media to first tweet only
                if i == 0 and media_ids:
                    variables["media"] = {"media_ids": media_ids}

                response = await self.http_client.graphql_request('CreateTweet', variables)

                if response and response.get('data', {}).get('create_tweet'):
                    tweet_id = response['data']['create_tweet']['tweet_id']
                    thread_tweets.append(tweet_id)
                    reply_to = tweet_id
                else:
                    raise Exception(f"Failed to create tweet {i + 1} in thread")

            return {
                "success": True,
                "tweet_ids": thread_tweets,
                "count": len(thread_tweets),
                "type": "thread",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error creating thread: {str(e)}")
            raise