import asyncio
import csv
from playwright.async_api import async_playwright
import logging
import os
from typing import Dict, Optional
from urllib.parse import quote
from sqlalchemy import select
from ..database import db_manager
from ..models.account import Account

logger = logging.getLogger(__name__)

async def change_username(
    old_auth_token: str,
    old_ct0: str,
    new_username: str,
    proxy_config: Optional[Dict] = None,
    headless: bool = False
) -> Dict:
    """Username change implementation with correct success verification"""
    try:
        async with async_playwright() as p:
            browser_args = {
                'headless': headless,
                'args': [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage'
                ]
            }

            # Configure proxy
            if proxy_config:
                try:
                    username = proxy_config.get('proxy_username')
                    password = proxy_config.get('proxy_password')
                    host = proxy_config.get('proxy_url')
                    port = proxy_config.get('proxy_port')

                    if not all([username, password, host, port]):
                        missing = []
                        if not username: missing.append('proxy_username')
                        if not password: missing.append('proxy_password')
                        if not host: missing.append('proxy_url')
                        if not port: missing.append('proxy_port')
                        raise ValueError(f"Missing proxy configuration: {', '.join(missing)}")

                    encoded_username = quote(str(username))
                    encoded_password = quote(str(password))
                    
                    browser_args['proxy'] = {
                        'server': f"http://{host}:{port}",
                        'username': username,
                        'password': password
                    }

                    logger.info(f"Proxy configured for {host}:{port}")

                except Exception as e:
                    logger.error(f"Failed to configure proxy: {str(e)}")
                    raise

            browser = await p.chromium.launch(**browser_args)
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 800},
                ignore_https_errors=True
            )

            try:
                # Set auth cookies
                await context.add_cookies([
                    {
                        'name': 'auth_token',
                        'value': old_auth_token,
                        'domain': '.twitter.com',
                        'path': '/'
                    },
                    {
                        'name': 'ct0',
                        'value': old_ct0,
                        'domain': '.twitter.com',
                        'path': '/'
                    }
                ])

                page = await context.new_page()
                page.set_default_timeout(15000)

                # Navigate to settings
                await page.goto(
                    'https://twitter.com/settings/screen_name',
                    wait_until='domcontentloaded',
                    timeout=15000
                )

                # Change username with increased timeout and better error handling
                try:
                    username_input = await page.wait_for_selector(
                        'input[name="typedScreenName"]',
                        timeout=30000  # Increased timeout to 30 seconds
                    )
                    if not username_input:
                        logger.error("Username input not found after waiting")
                        await page.screenshot(path='screenshots/no_username_input.png')
                        raise Exception("Username input not found")
                        
                    await username_input.fill(new_username)
                    
                    save_button = await page.wait_for_selector(
                        'text=Save',
                        timeout=30000
                    )
                    if not save_button:
                        logger.error("Save button not found")
                        await page.screenshot(path='screenshots/no_save_button.png')
                        raise Exception("Save button not found")
                        
                    await save_button.click()
                except Exception as e:
                    logger.error(f"Error during username change: {str(e)}")
                    await page.screenshot(path='screenshots/username_change_error.png')
                    raise Exception(f"Failed to change username: {str(e)}")

                # Wait for redirect after save
                try:
                    # Check for URL change and success - max 10 seconds
                    success = False
                    for _ in range(20):  # 20 checks * 0.5s = 10 seconds
                        current_url = page.url.lower()
                        if 'settings/account' in current_url:
                            success = True
                            logger.info("Username change successful - redirected to account data page")
                            break
                        elif 'error' in current_url or 'login' in current_url:
                            raise Exception("Redirected to error or login page")
                        await asyncio.sleep(0.5)

                    if not success:
                        # Check for error messages if no redirect
                        error = await page.query_selector(
                            'text=/This username has been taken|Username is invalid|Rate limit exceeded/'
                        )
                        if error:
                            error_text = await error.text_content()
                            raise Exception(error_text)
                        raise Exception("Username change failed - no redirect to account data page")

                except Exception as e:
                    # Take error screenshot
                    await page.screenshot(path=f'screenshots/error_change_{int(asyncio.get_event_loop().time())}.png')
                    raise Exception(f"Username change failed: {str(e)}")

                # Update account login in database
                session = db_manager.async_session()
                async with session as session:
                    account = await session.execute(
                        select(Account).where(Account.auth_token == old_auth_token)
                    )
                    account = account.scalar_one_or_none()
                    if account:
                        account.login = new_username
                        await session.commit()
                        logger.info(f"Updated account {account.account_no} login to {new_username}")
                    else:
                        logger.error("Could not find account to update login")

                # Update accounts1.csv
                try:
                    accounts_file = 'accounts1.csv'
                    temp_file = 'accounts1_temp.csv'
                    with open(accounts_file, 'r') as file:
                        reader = csv.DictReader(file)
                        fieldnames = reader.fieldnames
                        rows = list(reader)

                    # Update login in matching row
                    for row in rows:
                        if row.get('auth_token') == old_auth_token:
                            row['login'] = new_username
                            break

                    # Write updated data back
                    with open(temp_file, 'w', newline='') as file:
                        writer = csv.DictWriter(file, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(rows)

                    # Replace original file
                    os.replace(temp_file, accounts_file)
                    logger.info(f"Updated {accounts_file} with new login {new_username}")
                except Exception as e:
                    logger.error(f"Error updating accounts1.csv: {str(e)}")

                return {
                    'success': True,
                    'new_username': new_username,
                    'redirect_url': page.url
                }

            except Exception as e:
                try:
                    os.makedirs('screenshots', exist_ok=True)
                    await page.screenshot(path=f'screenshots/error_{int(asyncio.get_event_loop().time())}.png')
                    logger.error(f"Current URL at error: {page.url}")
                except:
                    pass
                raise e

            finally:
                await context.close()
                await browser.close()

    except Exception as e:
        logger.error(f"Username change failed: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
