import asyncio
import pytest
from backend.app.services.twitter_client import TwitterClient

async def test_twitter_client():
    """Test Twitter client functionality"""
    # Test configuration
    account_no = "test123"
    auth_token = "YOUR_AUTH_TOKEN"  # Replace with valid token
    ct0 = "YOUR_CT0"  # Replace with valid ct0
    
    # Test with proxy
    proxy_config = {
        "proxy_username": "test_user",
        "proxy_password": "test_pass",
        "proxy_url": "proxy.example.com",
        "proxy_port": "8080"
    }
    
    # Initialize client
    client = TwitterClient(
        account_no=account_no,
        auth_token=auth_token,
        ct0=ct0,
        proxy_config=proxy_config
    )
    
    try:
        # Test profile fetch (tests auth and proxy)
        profile = await client.get_profile("twitter")
        print("Profile fetch successful:", profile)
        
        # Test UTF-8 handling with non-ASCII username
        profile_utf8 = await client.get_profile("テスト")
        print("UTF-8 profile fetch successful:", profile_utf8)
        
        # Test tweet fetching with replies
        tweets = await client.get_user_tweets("twitter", count=5)
        print("Tweet fetch successful:", len(tweets['tweets']), "tweets found")
        
        # Verify replies structure
        for tweet in tweets['tweets']:
            if 'replies' in tweet:
                print(f"Found {len(tweet['replies'])} replies for tweet {tweet['id']}")
                
                # Check thread detection
                for reply in tweet['replies']:
                    if reply['type'] == 'thread':
                        print(f"Found thread with {len(reply['tweets'])} tweets")
                    else:
                        print(f"Found single reply from {reply['tweet']['author']}")
        
        # Test max_replies parameter
        max_replies = 3
        tweets_limited = await client.get_user_tweets("twitter", count=5, max_replies=max_replies)
        for tweet in tweets_limited['tweets']:
            if 'replies' in tweet:
                assert len(tweet['replies']) <= max_replies, f"Found more than {max_replies} replies"
        print(f"Max replies test successful (limit: {max_replies})")
        
    except Exception as e:
        print(f"Test failed: {str(e)}")
        raise
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_twitter_client())
