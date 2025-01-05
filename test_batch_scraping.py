import asyncio
import csv
import json
from pathlib import Path
import aiohttp
import time

# Test usernames - mix of tech, media, sports, and entertainment figures
TEST_USERNAMES = [
    "elonmusk",
    "BillGates",
    "BarackObama",
    "taylorswift13",
    "Cristiano",
    "NASA",
    "nytimes",
    "Google",
    "NBA",
    "TheRock"
]

API_BASE_URL = "http://localhost:9000"

async def create_test_csv():
    """Create a CSV file with test usernames"""
    csv_path = Path("test_usernames.csv")
    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Username'])  # Note: Capital U is required
        for username in TEST_USERNAMES:
            writer.writerow([username])
    return csv_path

async def upload_csv_for_task(session, csv_path, task_type, tweet_count=15):
    """Upload CSV file to create tasks"""
    url = f"{API_BASE_URL}/tasks/upload"
    params = {"task_type": task_type}
    if task_type == "scrape_tweets":
        params["count"] = tweet_count
    
    with open(csv_path, 'rb') as f:
        data = aiohttp.FormData()
        data.add_field('file', f, filename=csv_path.name)
        async with session.post(url, data=data, params=params) as response:
            return await response.json()

async def get_task_details(session, task_id):
    """Get details of a specific task"""
    url = f"{API_BASE_URL}/tasks/{task_id}"
    async with session.get(url) as response:
        return await response.json()

async def monitor_tasks(session, task_ids, task_type):
    """Monitor tasks until they complete"""
    print(f"\nMonitoring {task_type} tasks...")
    completed = set()
    start_time = time.time()
    
    while len(completed) < len(task_ids):
        for task_id in task_ids:
            if task_id in completed:
                continue
                
            task = await get_task_details(session, task_id)
            if task['status'] in ['completed', 'failed']:
                completed.add(task_id)
                print(f"Task {task_id} {task['status']}")
                
                if task['status'] == 'completed' and task['result']:
                    # Save result to file
                    result_dir = Path(f"scraping_results/{task_type}")
                    result_dir.mkdir(parents=True, exist_ok=True)
                    
                    result_file = result_dir / f"{task['input_params']['username']}.json"
                    with open(result_file, 'w') as f:
                        json.dump(task['result'], f, indent=2)
                        
                    if task_type == 'scrape_profile':
                        print(f"Profile saved for @{task['input_params']['username']}")
                    else:
                        tweet_count = len(task['result']['tweets'])
                        print(f"Saved {tweet_count} tweets for @{task['input_params']['username']}")
                        
        if len(completed) < len(task_ids):
            await asyncio.sleep(5)
            
    elapsed = time.time() - start_time
    print(f"\nAll {task_type} tasks completed in {elapsed:.1f} seconds")

async def main():
    """Run the end-to-end test"""
    print("Starting batch scraping test...")
    
    # Create test CSV
    csv_path = await create_test_csv()
    print(f"Created test CSV with {len(TEST_USERNAMES)} usernames")
    
    async with aiohttp.ClientSession() as session:
        # Test profile scraping
        print("\nStarting profile scraping tasks...")
        profile_response = await upload_csv_for_task(session, csv_path, "scrape_profile")
        if 'task_ids' in profile_response:
            print(f"Created {len(profile_response['task_ids'])} profile scraping tasks")
            await monitor_tasks(session, profile_response['task_ids'], "scrape_profile")
        else:
            print(f"Error creating tasks: {profile_response.get('detail', 'Unknown error')}")
            return
        
        # Test tweet scraping
        print("\nStarting tweet scraping tasks...")
        tweets_response = await upload_csv_for_task(session, csv_path, "scrape_tweets", tweet_count=15)
        if 'task_ids' in tweets_response:
            print(f"Created {len(tweets_response['task_ids'])} tweet scraping tasks")
            await monitor_tasks(session, tweets_response['task_ids'], "scrape_tweets")
        else:
            print(f"Error creating tasks: {tweets_response.get('detail', 'Unknown error')}")
            return
        
    # Cleanup
    csv_path.unlink()
    print("\nTest completed! Check scraping_results/ directory for output files")

if __name__ == "__main__":
    asyncio.run(main())
