import asyncio
from backend.app.database import init_db, get_session
from backend.app.models.account import Account, ValidationState

async def main():
    # Initialize database
    await init_db()
    
    async with get_session() as session:
        # Check if test worker exists
        account = Account(
            account_no="test_worker_1",
            act_type="worker",
            login="test_worker",
            auth_token="test_auth_token",
            ct0="test_ct0",
            is_active=True,
            validation_in_progress=ValidationState.COMPLETED
        )
        session.add(account)
        await session.commit()
        print("Added test worker account")

if __name__ == "__main__":
    asyncio.run(main())
