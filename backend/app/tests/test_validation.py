import asyncio
import logging
import httpx
import sys
import subprocess
import time
import signal
import os
from urllib.parse import unquote

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def wait_for_server(client: httpx.AsyncClient, max_retries: int = 5) -> bool:
    """Wait for the server to be ready"""
    for i in range(max_retries):
        try:
            response = await client.get("/accounts/")
            if response.status_code == 200:
                logger.info("Server is ready")
                return True
        except Exception as e:
            logger.warning(f"Server not ready (attempt {i+1}/{max_retries}): {e}")
        await asyncio.sleep(2)
    return False

async def test_account_validation():
    """Test account validation through the API endpoints"""
    
    try:
        # Create httpx client
        async with httpx.AsyncClient(
            base_url="http://localhost:9000",
            timeout=30.0,
            follow_redirects=True
        ) as client:
            # Wait for server to be ready
            if not await wait_for_server(client):
                logger.error("Server not available")
                return False

            # First, import accounts from CSV
            logger.info("Importing accounts from CSV")
            with open('accounts1.csv', 'rb') as f:
                files = {'file': ('accounts1.csv', f, 'text/csv')}
                response = await client.post("/accounts/import", files=files)
                
                if response.status_code != 200:
                    logger.error(f"Import failed with status {response.status_code}: {response.text}")
                    return False
                    
                import_result = response.json()
                logger.info(f"Import result: {import_result}")
                
                if import_result.get('successful', 0) == 0:
                    logger.error("No accounts were imported successfully")
                    return False

            # Test single account validation
            account_no = "act222"  # Using real account from CSV
            logger.info(f"Testing single account validation for {account_no}")
            
            # Verify account exists
            response = await client.get("/accounts/")
            if response.status_code != 200:
                logger.error(f"Failed to get accounts list: {response.text}")
                return False
                
            accounts = response.json()
            if not any(acc['account_no'] == account_no for acc in accounts):
                logger.error(f"Account {account_no} not found in database")
                return False

            # Validate single account
            logger.info(f"Validating account {account_no}")
            response = await client.post(f"/accounts/validate/{account_no}")
            
            if response.status_code != 200:
                logger.error(f"Validation request failed with status {response.status_code}: {response.text}")
                return False
                
            result = response.json()
            logger.info(f"Single account validation result: {result}")
            
            # Verify response format
            if not all(key in result for key in ['status', 'account_no', 'validation_result']):
                logger.error("Response missing required fields")
                return False
                
            if result['status'] != 'success':
                logger.error(f"Validation failed with status: {result['status']}")
                return False

            # Verify single account validation result
            validation_result = result['validation_result']
            logger.info(f"Account {account_no} validation result: {validation_result}")
            
            # Check if validation was successful
            if not validation_result.startswith('RECOVERED'):
                logger.error(f"Unexpected validation result: {validation_result}")
                return False

            # Test bulk validation
            logger.info("Testing bulk validation")
            response = await client.post("/accounts/validate-all", params={"threads": 6})
            
            if response.status_code != 200:
                logger.error(f"Bulk validation request failed with status {response.status_code}: {response.text}")
                return False
                
            bulk_result = response.json()
            logger.info(f"Bulk validation result: {bulk_result}")
            
            # Verify bulk validation response
            if not all(key in bulk_result for key in ['status', 'message', 'total']):
                logger.error("Bulk validation response missing required fields")
                return False
                
            if bulk_result['status'] != 'success':
                logger.error(f"Bulk validation failed with status: {bulk_result['status']}")
                return False
                
            if bulk_result['total'] == 0:
                logger.error("No accounts included in bulk validation")
                return False

            # Wait for first account to complete validation
            logger.info("Waiting for initial validation results...")
            max_retries = 5
            validation_started = False
            
            for i in range(max_retries):
                await asyncio.sleep(5)  # Wait 5 seconds between checks
                
                response = await client.get("/accounts/")
                if response.status_code != 200:
                    continue
                    
                accounts = response.json()
                # Check if any account has been validated
                for acc in accounts:
                    if acc.get('last_validation') and acc.get('last_validation_time'):
                        validation_started = True
                        logger.info(f"Validation confirmed working: {acc['account_no']} - {acc['last_validation']}")
                        break
                
                if validation_started:
                    break
                    
                logger.info(f"Waiting for validation results (attempt {i+1}/{max_retries})")
                
            if not validation_started:
                logger.error("No validation results found after waiting")
                return False

            logger.info("Validation test completed successfully")
            return True
            
    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        return False

async def main():
    """Run the test"""
    success = await test_account_validation()
    if success:
        print("✅ Validation test passed")
    else:
        print("❌ Validation test failed")

if __name__ == "__main__":
    asyncio.run(main())
