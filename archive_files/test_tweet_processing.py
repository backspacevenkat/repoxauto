import asyncio
import json
import logging
from backend.app.database import init_db, get_session
from backend.app.models.account import Account
from backend.app.services.twitter_client import TwitterClient
from sqlalchemy import select

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_tweet_processing():
    await init_db()
    
    async with get_session() as session:
        # Get worker account WACC164
        stmt = select(Account).where(
            Account.account_no == "WACC164",
            Account.act_type == "worker"
        )
        result = await session.execute(stmt)
        worker = result.scalar_one_or_none()
        
        if not worker:
            raise Exception("Worker account WACC164 not found!")
        
        # Configure proxy if available
        proxy_config = None
        if worker.proxy_url:
            proxy_config = {
                'proxy_url': worker.proxy_url,
                'proxy_port': worker.proxy_port,
                'proxy_username': worker.proxy_username,
                'proxy_password': worker.proxy_password
            }
        
        # Initialize Twitter client
        client = TwitterClient(
            account_no=worker.account_no,
            auth_token=worker.auth_token,
            ct0=worker.ct0,
            proxy_config=proxy_config,
            user_agent=worker.user_agent
        )
    
    try:
        # Get latest 15 tweets from Elon Musk
        result = await client.get_user_tweets("elonmusk", count=15)
        
        # Pretty print the tweets
        print("\nProcessed Tweets from @elonmusk:")
        print("=" * 80)
        
        for i, tweet in enumerate(result['tweets'], 1):
            print(f"\nTweet {i}:")
            print("-" * 40)
            print(json.dumps(tweet, indent=2))
            
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_tweet_processing())
