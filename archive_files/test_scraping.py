import asyncio
import json
from datetime import datetime
from backend.app.database import init_db, get_session
from backend.app.services.task_queue import TaskQueue

async def main():
    task_queue = None
    session = None
    try:
        # Initialize database
        await init_db()
        
        # Create task queue
        task_queue = TaskQueue(get_session)
        await task_queue.start()
        
        # Test profiles to scrape
        usernames = [
            "elonmusk",      # High profile tech figure
            "BarackObama",   # Political figure
            "BillGates",     # Tech/Philanthropy
            "sundarpichai",  # Tech CEO
            "satyanadella"   # Tech CEO
        ]
        
        print("\n=== Starting Profile & Tweet Scraping Test ===\n")
        print("Using real worker accounts with proxies to scrape Twitter data")
        print("This will respect Twitter's rate limits automatically\n")
        
        async with get_session() as session:
            # Create tasks for each profile
            profile_tasks = []
            tweet_tasks = []
            
            for username in usernames:
                print(f"\nQueuing tasks for @{username}...")
                
                # Create profile scraping task
                profile_task = await task_queue.add_task(
                    session,
                    "scrape_profile",
                    {"username": username}
                )
                profile_tasks.append(profile_task)
                print(f"- Profile scraping task created (ID: {profile_task.id})")
                
                # Create tweet scraping task
                tweet_task = await task_queue.add_task(
                    session,
                    "scrape_tweets",
                    {"username": username, "count": 15}
                )
                tweet_tasks.append(tweet_task)
                print(f"- Tweet scraping task created (ID: {tweet_task.id})")
            
            await session.commit()
            
            print(f"\nCreated {len(profile_tasks)} profile tasks and {len(tweet_tasks)} tweet tasks")
            print("\nMonitoring task completion (this may take a few minutes due to rate limiting)...\n")
            
            # Monitor tasks until all complete
            while True:
                all_complete = True
                completed_profiles = 0
                completed_tweets = 0
                
                # Check profile tasks
                for task in profile_tasks:
                    task = await task_queue.get_task_status(session, task.id)
                    if task.status == "completed":
                        completed_profiles += 1
                    elif task.status == "failed":
                        print(f"Profile task {task.id} failed: {task.error}")
                        completed_profiles += 1
                    else:
                        all_complete = False
                        
                # Check tweet tasks
                for task in tweet_tasks:
                    task = await task_queue.get_task_status(session, task.id)
                    if task.status == "completed":
                        completed_tweets += 1
                    elif task.status == "failed":
                        print(f"Tweet task {task.id} failed: {task.error}")
                        completed_tweets += 1
                    else:
                        all_complete = False
                
                print(f"\rProgress: Profiles {completed_profiles}/{len(profile_tasks)}, Tweets {completed_tweets}/{len(tweet_tasks)}", end="", flush=True)
                
                if all_complete:
                    print("\n\nAll tasks completed. Fetching results...\n")
                    break
                    
                await asyncio.sleep(1)
            
            # Print results
            for i, username in enumerate(usernames):
                print(f"=== Results for @{username} ===")
                
                # Get profile results
                profile_task = await task_queue.get_task_status(session, profile_tasks[i].id)
                if profile_task.status == "completed":
                    profile_data = profile_task.result["profile_data"]
                    print("\nProfile:")
                    print(f"- Name: {profile_data.get('name', 'N/A')}")
                    print(f"- Bio: {profile_data.get('bio', 'N/A')}")
                    print(f"- Followers: {profile_data.get('followers_count', 'N/A'):,}")
                    print(f"- Following: {profile_data.get('following_count', 'N/A'):,}")
                    print(f"- Location: {profile_data.get('location', 'N/A')}")
                    print(f"- Verified: {profile_data.get('verified', False)}")
                else:
                    print(f"\nProfile scraping failed: {profile_task.error}")
                
                # Get tweet results
                tweet_task = await task_queue.get_task_status(session, tweet_tasks[i].id)
                if tweet_task.status == "completed":
                    tweets = tweet_task.result["tweets"]
                    print(f"\nLatest {len(tweets)} Tweets:")
                    for j, tweet in enumerate(tweets[:3], 1):  # Show first 3 tweets
                        print(f"\n{j}. {tweet.get('text', 'N/A')}")
                        metrics = tweet.get('metrics', {})
                        print(f"   Likes: {metrics.get('like_count', 0):,}")
                        print(f"   Retweets: {metrics.get('retweet_count', 0):,}")
                        print(f"   Replies: {metrics.get('reply_count', 0):,}")
                        
                        # Show media info
                        media = tweet.get('media', [])
                        if media:
                            print(f"   Media: {len(media)} items")
                            for m in media:
                                print(f"   - {m.get('type', 'unknown')}: {m.get('url', 'N/A')}")
                        
                        # Show URLs
                        urls = tweet.get('urls', [])
                        if urls:
                            print(f"   URLs: {len(urls)} links")
                            for url in urls:
                                print(f"   - {url.get('display_url', 'N/A')}")
                    
                    if len(tweets) > 3:
                        print(f"\n... and {len(tweets) - 3} more tweets")
                else:
                    print(f"\nTweet scraping failed: {tweet_task.error}")
                
                print("\n" + "="*50 + "\n")
    
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        # Stop task queue
        if task_queue:
            await task_queue.stop()
        if session:
            await session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"\nError: {e}")
