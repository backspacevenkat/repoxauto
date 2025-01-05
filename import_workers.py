import asyncio
import csv
from backend.app.database import init_db, get_session
from backend.app.models.account import Account, ValidationState

async def import_workers():
    try:
        # Initialize database
        await init_db()
        print("Database initialized")
        
        async with get_session() as session:
            print("Opening accounts1.csv...")
            # Read CSV file
            with open('accounts1.csv', 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row['act_type'].lower() == 'worker':
                        # Check if account exists
                        print(f"Processing worker account: {row['account_no']}")
                        account = Account(
                            account_no=row['account_no'],
                            act_type='worker',
                            login=row['login'],
                            auth_token=row['auth_token'],
                            ct0=row['ct0'],
                            proxy_url=row['proxy_url'],
                            proxy_port=row['proxy_port'],
                            proxy_username=row['proxy_username'],
                            proxy_password=row['proxy_password'],
                            user_agent=row['user_agent'],
                            is_active=True,
                            validation_in_progress='COMPLETED'
                        )
                        session.add(account)
                        try:
                            await session.commit()
                            print(f"Successfully added worker account: {row['account_no']}")
                        except Exception as e:
                            await session.rollback()
                            print(f"Error adding account {row['account_no']}: {str(e)}")

    except Exception as e:
        print(f"Error during import: {str(e)}")
        raise

if __name__ == "__main__":
    print("Starting worker account import...")
    asyncio.run(import_workers())
    print("Import process completed")
