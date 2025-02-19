from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
import json
import base64
from typing import Optional, Dict, List
import logging
from urllib.parse import unquote, urlparse, parse_qs
from ..services.account_validator import validate_account
from ..services.browser_launcher import BrowserLauncher, BrowserManager

router = APIRouter()
logger = logging.getLogger(__name__)

def extract_account_id(request: Request, auth_token: str) -> str:
    """Extract account ID from request"""
    try:
        # First try to get from referrer
        referrer = request.headers.get('referer')
        if referrer:
            logger.info(f"Found referrer: {referrer}")
            parsed = urlparse(referrer)
            
            # Try to find account ID in referrer path
            path_parts = [p for p in parsed.path.split('/') if p]  # Remove empty strings
            logger.info(f"Referrer path parts: {path_parts}")
            
            # Look for WACC pattern in path parts
            for part in path_parts:
                if part.startswith('WACC'):
                    logger.info(f"Found WACC ID in referrer path: {part}")
                    return part

            # Try to find account ID in referrer query params
            query_params = parse_qs(parsed.query)
            if 'account' in query_params:
                account_id = query_params['account'][0]
                if account_id.startswith('WACC'):
                    logger.info(f"Found WACC ID in referrer query: {account_id}")
                    return account_id

        # Try current URL path
        path_parts = [p for p in request.url.path.split('/') if p]  # Remove empty strings
        logger.info(f"Current URL path parts: {path_parts}")
        
        # Look for WACC pattern in path parts
        for part in path_parts:
            if part.startswith('WACC'):
                logger.info(f"Found WACC ID in URL path: {part}")
                return part

        # Try to get from auth data
        try:
            auth_data_str = base64.b64decode(unquote(request.query_params.get('data', ''))).decode()
            auth_data = json.loads(auth_data_str)
            if 'account_id' in auth_data:
                account_id = auth_data['account_id']
                if account_id.startswith('WACC'):
                    logger.info(f"Found WACC ID in auth data: {account_id}")
                    return account_id
        except Exception as e:
            logger.error(f"Error extracting from auth data: {str(e)}")

        # Try to get from query parameters
        query_params = dict(request.query_params)
        if 'account' in query_params:
            account_id = query_params['account']
            if account_id.startswith('WACC'):
                logger.info(f"Found WACC ID in query params: {account_id}")
                return account_id

        # Fallback to auth token part
        account_id = auth_token[:8]
        logger.info(f"Using fallback account ID from auth token: {account_id}")
        return account_id

    except Exception as e:
        logger.error(f"Error extracting account ID: {str(e)}")
        logger.error(f"Request URL: {request.url}")
        logger.error(f"Referrer: {request.headers.get('referer')}")
        logger.error(f"Query params: {dict(request.query_params)}")
        return auth_token[:8]  # Fallback to auth token part

@router.get("/auth-twitter")
async def auth_twitter(data: str, request: Request):
    """Handle authenticated Twitter session"""
    browser = None
    try:
        # Log request details
        logger.info(f"Auth request - URL: {request.url}")
        logger.info(f"Auth request - Headers: {dict(request.headers)}")
        
        # URL decode first since the data might be double encoded
        data = unquote(data)
        
        # Decode auth data
        try:
            auth_data_str = base64.b64decode(data).decode()
            auth_data = json.loads(auth_data_str)
            logger.info(f"Decoded auth data: {json.dumps(auth_data, indent=2)}")
        except Exception as e:
            logger.error(f"Error decoding auth data: {str(e)}")
            logger.error(f"Raw data: {data}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid auth data format: {str(e)}"
            )

        # Extract credentials and proxy info
        auth_token = auth_data.get('auth_token')
        ct0 = auth_data.get('ct0')
        user_agent = auth_data.get('user_agent')
        proxy_url = auth_data.get('proxy_url')
        
        # Extract account ID
        account_id = extract_account_id(request, auth_token)
        logger.info(f"Using account ID: {account_id}")

        if not all([auth_token, ct0, proxy_url]):
            missing = []
            if not auth_token: missing.append('auth_token')
            if not ct0: missing.append('ct0')
            if not proxy_url: missing.append('proxy_url')
            raise HTTPException(
                status_code=400,
                detail=f"Missing required auth data: {', '.join(missing)}"
            )

        # Check if browser instance already exists
        existing_browser = BrowserManager.get_instance(account_id)
        if existing_browser:
            # Check if it's still alive
            if await existing_browser.is_alive():
                return HTMLResponse(content=create_html_response(
                    True,
                    "Browser session already active",
                    proxy_info="Using existing session",
                    is_new=False,
                    account_id=account_id
                ))
            else:
                # Close dead session
                await existing_browser.close()

        # Parse proxy URL components
        try:
            parsed_proxy = urlparse(proxy_url if '://' in proxy_url else f'http://{proxy_url}')
            proxy_host = parsed_proxy.hostname or proxy_url.split(':')[0]
            proxy_port = str(parsed_proxy.port) if parsed_proxy.port else proxy_url.split(':')[1] if ':' in proxy_url else "80"
            proxy_username = auth_data.get('proxy_username', '')
            proxy_password = auth_data.get('proxy_password', '')
            
            logger.info(f"Parsed proxy config - Host: {proxy_host}, Port: {proxy_port}")
        except Exception as e:
            logger.error(f"Error parsing proxy URL: {e}")
            logger.error(f"Proxy URL: {proxy_url}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid proxy URL format: {proxy_url}"
            )

        # Create proxy config
        proxy_config = {
            'host': proxy_host,
            'port': proxy_port,
            'username': proxy_username,
            'password': proxy_password
        }

        # Launch browser
        browser = BrowserLauncher(account_id)
        success = await browser.launch(
            auth_token=auth_token,
            ct0=ct0,
            proxy_config=proxy_config,
            user_agent=user_agent
        )

        if not success:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to launch authenticated browser session for account {account_id}"
            )

        return HTMLResponse(content=create_html_response(
            True,
            "Browser session started successfully",
            proxy_info=f"{proxy_host}:{proxy_port}",
            is_new=True,
            account_id=account_id
        ))

    except Exception as e:
        logger.error(f"Error in auth_twitter: {str(e)}")
        if browser:
            await browser.close()
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cleanup/{account_id}")
async def cleanup_browser(account_id: str):
    """Cleanup browser instance for account"""
    try:
        browser = BrowserManager.get_instance(account_id)
        if browser:
            await browser.close()
            return {"status": "success", "message": f"Browser session cleaned up for account {account_id}"}
        return {"status": "success", "message": f"No active browser session for account {account_id}"}
    except Exception as e:
        logger.error(f"Error cleaning up browser for account {account_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cleanup-all")
async def cleanup_all_browsers():
    """Cleanup all browser instances"""
    try:
        await BrowserManager.cleanup_all()
        return {"status": "success", "message": "All browser sessions cleaned up"}
    except Exception as e:
        logger.error(f"Error cleaning up all browsers: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status/{account_id}")
async def get_browser_status(account_id: str):
    """Get browser status for account"""
    try:
        browser = BrowserManager.get_instance(account_id)
        if not browser:
            return {
                "status": "inactive",
                "message": f"No browser session for account {account_id}"
            }
        
        is_alive = await browser.is_alive()
        return {
            "status": "active" if is_alive else "dead",
            "message": "Browser session is running" if is_alive else "Browser session is dead"
        }
    except Exception as e:
        logger.error(f"Error checking browser status for account {account_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sessions")
async def get_browser_sessions():
    """Get all active browser sessions"""
    try:
        sessions = []
        for account_id, browser in BrowserManager._instances.items():
            try:
                is_alive = await browser.is_alive()
                sessions.append({
                    "account_id": account_id,
                    "status": "active" if is_alive else "dead",
                    "message": "Browser session is running" if is_alive else "Browser session is dead"
                })
            except Exception as e:
                logger.error(f"Error checking status for account {account_id}: {str(e)}")
                sessions.append({
                    "account_id": account_id,
                    "status": "error",
                    "message": f"Error checking status: {str(e)}"
                })
        
        return {
            "total_sessions": len(sessions),
            "sessions": sessions
        }
    except Exception as e:
        logger.error(f"Error getting browser sessions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

def create_html_response(success: bool, message: str, proxy_info: str = "", is_new: bool = True, account_id: str = "") -> str:
    """Create HTML response with status and message"""
    status_class = "success" if success else "error"
    status_text = "Success" if success else "Error"
    border_color = "#4caf50" if success else "#f44336"
    bg_color = "#f1f8e9" if success else "#ffebee"
    text_color = "#4caf50" if success else "#f44336"
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Twitter Authentication</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 600px;
                margin: 40px auto;
                padding: 20px;
                text-align: center;
            }}
            .status {{
                margin: 20px 0;
                padding: 15px;
                border: 1px solid {border_color};
                border-radius: 5px;
                background: {bg_color};
                color: {text_color};
            }}
            .message {{
                margin: 20px 0;
                color: #666;
            }}
            .browser-info {{
                margin: 20px 0;
                padding: 15px;
                border: 1px solid #2196f3;
                border-radius: 5px;
                background: #e3f2fd;
                color: #2196f3;
                text-align: left;
            }}
            .browser-info h4 {{
                margin: 0 0 10px 0;
            }}
            .browser-info ul {{
                margin: 0;
                padding-left: 20px;
            }}
            .browser-info li {{
                margin: 5px 0;
            }}
            .note {{
                margin-top: 20px;
                padding: 10px;
                background: #fff3e0;
                border: 1px solid #ff9800;
                border-radius: 4px;
                color: #ff9800;
                font-size: 0.9em;
            }}
            .tips {{
                margin-top: 20px;
                text-align: left;
                font-size: 0.9em;
                color: #666;
            }}
            .tips h4 {{
                color: #333;
                margin: 0 0 10px 0;
            }}
            .tips ul {{
                margin: 0;
                padding-left: 20px;
            }}
            .tips li {{
                margin: 5px 0;
            }}
        </style>
    </head>
    <body>
        <h2>Twitter Authentication</h2>
        
        <div class="status">
            <h3>Browser Session {status_text}</h3>
        </div>

        <div class="message">
            <p>{message}</p>
        </div>

        <div class="browser-info">
            <h4>Browser Information:</h4>
            <ul>
                <li>Account: {account_id}</li>
                <li>Proxy: {proxy_info}</li>
                <li>Authentication: Active</li>
                <li>Status: Connected</li>
                <li>Session: {'New' if is_new else 'Existing'}</li>
            </ul>
        </div>

        <div class="note">
            <p>You can close this window. The browser session will remain active.</p>
        </div>

        <div class="tips">
            <h4>Tips:</h4>
            <ul>
                <li>The browser window is configured with your account's proxy settings</li>
                <li>All Twitter interactions will use your account's authentication</li>
                <li>The session will persist until you close the browser window</li>
                <li>You can reopen this page to check session status or start a new session</li>
            </ul>
        </div>
    </body>
    </html>
    """
