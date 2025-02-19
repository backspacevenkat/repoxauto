import asyncio
import logging
import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from backend.app.database import init_db, get_session
from backend.app.models.account import Account
from backend.app.services.twitter_client import TwitterClient
from sqlalchemy import select

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BatchProcessor:
    def __init__(self, batch_size: int = 10, output_dir: str = "scraping_results"):
        self.batch_size = batch_size
        self.workers: List[TwitterClient] = []
        self.current_worker = 0
        self.output_dir = output_dir
        self.rate_limits: Dict[str, datetime] = {}  # Track rate limits per worker
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.join(output_dir, "profiles"), exist_ok=True)
        os.makedirs(os.path.join(output_dir, "tweets"), exist_ok=True)
        
    async def initialize_workers(self):
        """Initialize worker accounts from database"""
        await init_db()
        async with get_session() as session:
            stmt = select(Account).where(Account.act_type == 'worker')
            result = await session.execute(stmt)
            accounts = result.scalars().all()
            
            for account in accounts:
                if account.account_no.startswith('test'):
                    continue
                    
                proxy_config = None
                if account.proxy_url:
                    proxy_config = {
                        'proxy_url': account.proxy_url,
                        'proxy_port': account.proxy_port,
                        'proxy_username': account.proxy_username,
                        'proxy_password': account.proxy_password
                    }
                
                client = TwitterClient(
                    account_no=account.account_no,
                    auth_token=account.auth_token,
                    ct0=account.ct0,
                    proxy_config=proxy_config,
                    user_agent=account.user_agent
                )
                self.workers.append(client)
                
        logger.info(f"Initialized {len(self.workers)} worker accounts")
    
    def get_next_worker(self) -> Optional[TwitterClient]:
        """Get next available worker"""
        attempts = 0
        while attempts < len(self.workers):
            worker = self.workers[self.current_worker]
            self.current_worker = (self.current_worker + 1) % len(self.workers)
            
            # Check if worker is rate limited
            if worker.account_no in self.rate_limits:
                if datetime.now() < self.rate_limits[worker.account_no]:
                    attempts += 1
                    continue
                else:
                    del self.rate_limits[worker.account_no]
                    
            return worker
            
        return None  # All workers are rate limited
    
    async def process_batch(self, usernames: List[str]) -> Dict[str, Any]:
        """Process a batch of usernames"""
        tasks = []
        results = {
            'profiles': {},
            'tweets': {},
            'errors': {}
        }
        
        # Create tasks for each username
        for username in usernames:
            worker = self.get_next_worker()
            tasks.append(self.process_user(worker, username, results))
            
        # Wait for all tasks to complete
        await asyncio.gather(*tasks)
        return results
    
    def save_results(self, username: str, profile: Dict = None, tweets: Dict = None):
        """Save results to files"""
        if profile:
            profile_path = os.path.join(self.output_dir, "profiles", f"{username}.json")
            with open(profile_path, 'w') as f:
                json.dump(profile, f, indent=2)
                
        if tweets:
            tweets_path = os.path.join(self.output_dir, "tweets", f"{username}.json")
            with open(tweets_path, 'w') as f:
                json.dump(tweets, f, indent=2)
    
    def load_processed_users(self) -> set:
        """Load list of already processed users"""
        processed = set()
        profile_dir = os.path.join(self.output_dir, "profiles")
        for filename in os.listdir(profile_dir):
            if filename.endswith('.json'):
                processed.add(filename[:-5])  # Remove .json extension
        return processed
    
    async def process_user(self, worker: TwitterClient, username: str, results: Dict, retries: int = 3):
        """Process a single username with retries"""
        for attempt in range(retries):
            try:
                # Get profile
                profile = await worker.get_profile(username)
                results['profiles'][username] = profile
                self.save_results(username, profile=profile)
                
                # Get tweets
                tweets = await worker.get_user_tweets(username, count=100)
                results['tweets'][username] = tweets
                self.save_results(username, tweets=tweets)
                
                logger.info(f"Successfully processed {username} using {worker.account_no}")
                return
                
            except Exception as e:
                logger.error(f"Attempt {attempt + 1}/{retries} failed for {username} with {worker.account_no}: {str(e)}")
                
                if 'rate limit' in str(e).lower():
                    # Mark worker as rate limited
                    self.rate_limits[worker.account_no] = datetime.now() + timedelta(minutes=15)
                    
                    # Try to get another worker
                    new_worker = self.get_next_worker()
                    if new_worker:
                        worker = new_worker
                        continue
                    else:
                        # All workers rate limited, sleep and retry
                        await asyncio.sleep(60)
                        continue
                        
                elif attempt < retries - 1:
                    # For other errors, wait briefly and retry
                    await asyncio.sleep(5)
                    continue
                    
                # Final attempt failed
                results['errors'][username] = str(e)
    
    async def process_all(self, usernames: List[str]) -> Dict[str, Any]:
        """Process all usernames in batches"""
        await self.initialize_workers()
        
        all_results = {
            'profiles': {},
            'tweets': {},
            'errors': {},
            'stats': {
                'total': len(usernames),
                'successful': 0,
                'failed': 0,
                'start_time': datetime.now().isoformat(),
                'end_time': None
            }
        }
        
        # Process in batches
        for i in range(0, len(usernames), self.batch_size):
            batch = usernames[i:i + self.batch_size]
            logger.info(f"Processing batch {i//self.batch_size + 1}/{(len(usernames)-1)//self.batch_size + 1}")
            
            results = await self.process_batch(batch)
            
            # Merge results
            all_results['profiles'].update(results['profiles'])
            all_results['tweets'].update(results['tweets'])
            all_results['errors'].update(results['errors'])
            
            # Update stats
            all_results['stats']['successful'] += len(results['profiles'])
            all_results['stats']['failed'] += len(results['errors'])
            
            # Progress update
            progress = (i + len(batch)) / len(usernames) * 100
            logger.info(f"Progress: {progress:.1f}% ({i + len(batch)}/{len(usernames)})")
            
            # Small delay between batches
            await asyncio.sleep(1)
        
        # Close all workers
        for worker in self.workers:
            await worker.close()
            
        all_results['stats']['end_time'] = datetime.now().isoformat()
        return all_results

async def main():
    # Example usernames to scrape
    usernames = [
        "twitter",
        "elonmusk",
        "BillGates",
        "BarackObama",
        "NASA",
        "Google",
        "Microsoft",
        "Apple",
        "Amazon",
        "Tesla"
    ]
    
    processor = BatchProcessor(batch_size=3)
    # Skip already processed users
    processed = processor.load_processed_users()
    usernames_to_process = [u for u in usernames if u not in processed]
    
    if not usernames_to_process:
        logger.info("All users have already been processed!")
        return
        
    logger.info(f"Processing {len(usernames_to_process)} users (skipping {len(processed)} already processed)")
    results = await processor.process_all(usernames_to_process)
    
    # Print summary
    logger.info("\nScraping Summary:")
    logger.info("=" * 50)
    logger.info(f"Total accounts processed: {results['stats']['total']}")
    logger.info(f"Successful: {results['stats']['successful']}")
    logger.info(f"Failed: {results['stats']['failed']}")
    logger.info(f"Start time: {results['stats']['start_time']}")
    logger.info(f"End time: {results['stats']['end_time']}")
    
    # Print some sample data
    if results['profiles']:
        sample_user = next(iter(results['profiles']))
        logger.info(f"\nSample profile data for {sample_user}:")
        logger.info(f"Followers: {results['profiles'][sample_user]['metrics']['followers_count']}")
        logger.info(f"Tweets found: {len(results['tweets'][sample_user]['tweets'])}")

if __name__ == "__main__":
    asyncio.run(main())
