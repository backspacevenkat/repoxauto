import asyncio
from sqlalchemy import select
from backend.app.database import async_session
from backend.app.models.account import Account, ValidationState

async def check_worker_accounts():
    """Check status of worker accounts in the database"""
    print("\n=== Checking Worker Accounts ===\n")
    
    async with async_session() as session:
        try:
            # Query worker accounts
            stmt = select(Account).where(Account.act_type == 'worker')
            result = await session.execute(stmt)
            workers = list(result.scalars().all())  # Convert to list to avoid session issues
            
            if not workers:
                print("❌ No worker accounts found in database!")
                print("Please add worker accounts before running tasks.")
                return
            
            print(f"Found {len(workers)} worker accounts:")
            
            for worker in workers:
                status = "✅" if worker.can_process_task() else "❌"
                print(f"\n{status} Account: {worker.account_no}")
                print(f"   Active: {worker.is_active}")
                print(f"   Auth Token: {'Present' if worker.auth_token else 'Missing'}")
                print(f"   CT0: {'Present' if worker.ct0 else 'Missing'}")
                print(f"   Validation State: {worker.validation_in_progress}")
                print(f"   Rate Limited: {worker.is_rate_limited}")
                print(f"   Tasks Completed: {worker.total_tasks_completed}")
                print(f"   Tasks Failed: {worker.total_tasks_failed}")
                print(f"   Success Rate: {worker.success_rate:.1f}%")
                
                if not worker.can_process_task():
                    print("   Cannot process tasks because:")
                    if not worker.is_active:
                        print("   - Account is not active")
                    if worker.is_rate_limited:
                        print("   - Account is rate limited")
                    if not worker.auth_token or not worker.ct0:
                        print("   - Missing auth tokens")
                    if worker.validation_in_progress in [ValidationState.VALIDATING, ValidationState.RECOVERING]:
                        print(f"   - Account is {worker.validation_in_progress}")
            
            ready_workers = sum(1 for w in workers if w.can_process_task())
            print(f"\nReady to process tasks: {ready_workers}/{len(workers)} workers")
            
        except Exception as e:
            print(f"Error checking worker accounts: {str(e)}")
            raise

if __name__ == "__main__":
    asyncio.run(check_worker_accounts())
