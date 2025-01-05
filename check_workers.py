import asyncio
import logging
from backend.app.database import init_db, get_session
from backend.app.models.account import Account
from backend.app.services.twitter_client import TwitterClient
from sqlalchemy import select

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_worker(worker: Account):
    """Test a worker account with the Twitter client"""
    logger.info(f"\nTesting worker account: {worker.account_no}")
    
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
        # Test basic profile fetch with detailed response logging
        logger.info("Testing profile fetch...")
        logger.info(f"Using auth_token: {worker.auth_token[:10]}... ct0: {worker.ct0[:10]}...")
        
        if worker.proxy_url:
            logger.info(f"Using proxy: {worker.proxy_url}:{worker.proxy_port}")
            
        profile = await client.get_profile("twitter")
        logger.info(f"✓ Profile fetch successful - User ID: {profile.get('id')}")
        logger.info(f"All tests passed for account {worker.account_no}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Test failed for account {worker.account_no}: {str(e)}")
        return False
    finally:
        await client.close()

async def main():
    await init_db()
    
    async with get_session() as session:
        # Get all worker accounts
        stmt = select(Account).where(Account.act_type == 'worker')
        result = await session.execute(stmt)
        workers = result.scalars().all()
        
        if not workers:
            logger.error("No worker accounts found!")
            return
            
        logger.info(f"\nTesting {len(workers)} worker accounts...")
        
        # Test each worker
        success_count = 0
        for worker in workers:
            if await test_worker(worker):
                success_count += 1
                
        # Print summary
        logger.info("\nTest Summary:")
        logger.info("=" * 50)
        logger.info(f"Total accounts tested: {len(workers)}")
        logger.info(f"Successful: {success_count}")
        logger.info(f"Failed: {len(workers) - success_count}")

if __name__ == "__main__":
    asyncio.run(main())
