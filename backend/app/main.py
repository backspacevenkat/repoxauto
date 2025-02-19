from fastapi import FastAPI, HTTPException, status, WebSocket, WebSocketDisconnect, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Dict, Set, List
import uvicorn
import logging
import os
import sys
import json
import asyncio
from datetime import datetime
import redis.asyncio as redis
from contextlib import asynccontextmanager
from sqlalchemy import select, text, func

from .database import init_db, db_manager, monitor_db_health
from .models.account import Account, ValidationState
from .models.follow_settings import FollowSettings
from .routers import accounts, tasks, settings, search, actions, auth, profile_updates, follow, act_setup
from .services.task_manager import TaskManager
from .services.follow_scheduler import FollowScheduler

# Configure logging
os.makedirs('logs', exist_ok=True)

# Create custom formatter
formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s'
)

# Create file handler
file_handler = logging.FileHandler('logs/app.log')
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.INFO)

# Create console handler with higher threshold
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
console_handler.setLevel(logging.WARNING)  # Only WARNING and above go to console

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# Configure uvicorn access logger to reduce noise
uvicorn_logger = logging.getLogger("uvicorn.access")
uvicorn_logger.setLevel(logging.WARNING)  # Only log warnings and errors

# Get logger for this module
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Xauto API",
    description="Twitter Account Management and Automation System",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    redirect_slashes=False,
    default_response_class=JSONResponse
)

# Configure CORS
origins = [
    "http://127.0.0.1:3003",    # Frontend development server
    "http://localhost:3003",     # Frontend development server (alternate)
    "http://127.0.0.1:9000",    # Backend server
    "ws://127.0.0.1:9000",      # WebSocket backend server
    "*"                         # Allow all origins in development
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"]  # Important for file downloads
)

# WebSocket CORS middleware
@app.middleware("http")
async def add_cors_headers(request, call_next):
    response = await call_next(request)
    if request.url.path == "/ws":
        # Allow all origins for WebSocket in development
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Set
import time

class ConnectionState(Enum):
    SETUP_PENDING = "setup_pending"    # Initial state during setup
    SETUP_COMPLETE = "setup_complete"  # Setup finished, ready for messages
    CONNECTED = "connected"            # Fully connected and ready
    DISCONNECTING = "disconnecting"    # Starting disconnect
    DISCONNECTED = "disconnected"      # Disconnect complete
    CLOSING = "closing"                # Starting close
    CLOSED = "closed"                  # Close complete
    ERROR = "error"                    # Error state

@dataclass
class ConnectionInfo:
    websocket: WebSocket
    state: ConnectionState
    last_heartbeat: float
    heartbeat_interval: float
    missed_heartbeats: int
    setup_complete: bool = False           # Track setup completion
    setup_time: Optional[float] = None     # When setup started
    cleanup_task: Optional[asyncio.Task] = None
    close_frame_sent: bool = False
    close_frame_received: bool = False
    error_message: Optional[str] = None    # Store error details

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> str:
        """Connect a client and return its ID"""
        await websocket.accept()
        client_id = f"{websocket.client.host}:{websocket.client.port}"
        
        async with self._lock:
            self.active_connections[client_id] = websocket
            
        return client_id

    async def disconnect(self, client_id: str):
        """Disconnect a client"""
        async with self._lock:
            if client_id in self.active_connections:
                del self.active_connections[client_id]

    async def send_message(self, client_id: str, message: dict):
        """Send message to a specific client"""
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(message)

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients"""
        if not isinstance(message, dict):
            logger.error(f"Invalid message type for broadcast: {type(message)}")
            return

        # Add timestamp if not present
        if 'timestamp' not in message:
            message['timestamp'] = datetime.utcnow().isoformat()

        # Get copy of connections to avoid holding lock during sends
        async with self._lock:
            connections = list(self.active_connections.items())

        # Send to each client
        for client_id, websocket in connections:
            try:
                await websocket.send_json(message)
            except WebSocketDisconnect:
                logger.info(f"Client {client_id} disconnected during broadcast")
                await self.disconnect(client_id)
            except Exception as e:
                logger.error(f"Error broadcasting to client {client_id}: {e}")
                try:
                    await self.disconnect(client_id)
                except Exception as cleanup_err:
                    logger.error(f"Error cleaning up connection {client_id}: {cleanup_err}")

# Create a connection manager instance
manager = ConnectionManager()

# Make ConnectionManager available to routers
app.state.connection_manager = manager

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    client_id = None
    try:
        client_id = await manager.connect(websocket)
        logger.info(f"New WebSocket connection from {client_id}")
        
        # Send initial connection message
        await websocket.send_json({
            "type": "connection_established",
            "message": "Connected to server",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Broadcast connection event
        await manager.broadcast({
            "type": "client_connected",
            "client_id": client_id
        })
        
        while True:
            try:
                data = await websocket.receive_json()
                message_type = data.get("type")
                
                if message_type == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                else:
                    # Process and broadcast the message
                    await manager.broadcast({
                        "type": message_type,
                        "data": data,
                        "source_client": client_id
                    })
                    
            except WebSocketDisconnect:
                logger.info(f"Client {client_id} disconnected normally")
                break
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON from client {client_id}")
                continue
            except Exception as e:
                logger.error(f"Error in websocket loop for {client_id}: {e}")
                break
                
    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {e}")
    finally:
        if client_id:
            await manager.disconnect(client_id)
            logger.info(f"WebSocket connection closed for {client_id}")
            
            # Broadcast disconnection event
            try:
                await manager.broadcast({
                    "type": "client_disconnected",
                    "client_id": client_id
                })
            except Exception as e:
                logger.error(f"Error broadcasting disconnect event: {e}")

async def handle_websocket_message(websocket: WebSocket, data: dict):
    """Handle different types of WebSocket messages"""
    try:
        message_type = data.get("type")
        if message_type == "subscribe":
            # Handle subscription
            pass
        elif message_type == "unsubscribe":
            # Handle unsubscription
            pass
        # Add other message type handlers as needed
    except Exception as e:
        logger.error(f"Error in handle_websocket_message: {e}")
        raise

async def broadcast_message(message: dict):
    """Broadcast a message to all connected WebSocket clients"""
    try:
        message["timestamp"] = datetime.utcnow().isoformat()
        await manager.broadcast(message)
    except Exception as e:
        logger.error(f"Error broadcasting message: {e}")

# Create API router with prefix
api_router = APIRouter(prefix="/api")

# Include all routers under the API router
api_router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])  # Add back the prefix
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(search.router, tags=["search"])
api_router.include_router(actions.router, prefix="/actions", tags=["actions"])
api_router.include_router(auth.router, prefix="", tags=["auth"])
api_router.include_router(profile_updates.router, tags=["profile-updates"])
api_router.include_router(follow.router, tags=["follow"])
api_router.include_router(act_setup.router, prefix="/accounts/setup", tags=["act-setup"])

# Include the API router in the app
app.include_router(api_router)

# Configure logging for follow system
logging.getLogger('app.services.follow_scheduler').setLevel(logging.INFO)
logging.getLogger('app.routers.follow').setLevel(logging.INFO)

# Create instances (will be initialized during startup)
follow_scheduler = None

# Application state
app_state = {
    "startup_time": None,
    "is_healthy": False,
    "db_connected": False,
    "task_queue_running": False
}

@app.on_event("startup")
async def startup_event():
    """Initialize application on startup"""
    try:
        logger.info("Starting application initialization...")
        
        # Initialize database
        if not await db_manager.initialize():
            raise Exception("Database initialization failed")
            
        await init_db()

        # Initialize task manager with session factory
        try:
            task_manager = await TaskManager.get_instance(db_manager.async_session)
            app.state.task_manager = task_manager
            app_state["task_queue_running"] = False  # Ensure initial state is stopped
            logger.info("Task manager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize task manager: {e}")
            app_state["task_queue_running"] = False
            raise
        
        # Verify database has tables
        async with db_manager.async_session() as session:
            result = await session.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            tables = result.scalars().all()
            logger.info(f"Database tables: {tables}")
            
            # Check for accounts
            result = await session.execute(select(func.count()).select_from(Account))
            count = result.scalar()
            logger.info(f"Total accounts in database: {count}")
            
            # Initialize follow settings if needed
            settings_query = await session.execute(select(FollowSettings).order_by(FollowSettings.id.desc()))
            settings = settings_query.scalars().first()
            
            # Delete any extra settings rows, keeping only the most recent
            if settings:
                # Delete all rows except the most recent one
                await session.execute(
                    text("DELETE FROM follow_settings WHERE id NOT IN (SELECT id FROM follow_settings ORDER BY id DESC LIMIT 1)")
                )
                await session.commit()
            else:
                logger.info("Creating default follow settings")
                default_settings = FollowSettings(
                    max_follows_per_interval=1,
                    interval_minutes=16,
                    max_follows_per_day=30,
                    internal_ratio=5,
                    external_ratio=25,
                    min_following=300,
                    max_following=400,
                    schedule_groups=3,
                    schedule_hours=8,
                    is_active=False,
                    last_updated=datetime.utcnow()
                )
                session.add(default_settings)
                await session.commit()
                logger.info("Default follow settings created")
            
            # Initialize follow scheduler
            app.state.follow_scheduler = FollowScheduler(db_manager.async_session)
            logger.info("Follow scheduler initialized")
            
            # Initialize but don't start scheduler
            logger.info("Follow scheduler initialized but not started")
            
            # Set app state
            app_state["is_healthy"] = True
            app_state["db_connected"] = True
            app_state["startup_time"] = datetime.utcnow()
            
        logger.info("Application initialization complete")
        
    except Exception as e:
        logger.error(f"Failed to initialize application: {e}")
        app_state["is_healthy"] = False
        app_state["db_connected"] = False
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown."""
    try:
        # Mark app as unhealthy first
        app_state["is_healthy"] = False

        # Cleanup task manager
        if hasattr(app.state, 'task_manager'):
            await app.state.task_manager.cleanup()
            TaskManager.reset_instance()
            logger.info("Task manager cleaned up")
        
        # Stop services
        try:
            async with asyncio.timeout(5):  # 5 second timeout
                # Stop follow scheduler if running
                if hasattr(app.state, 'follow_scheduler'):
                    await app.state.follow_scheduler.stop()
                    logger.info("Follow scheduler stopped")
                
                # Stop database monitor task
                if hasattr(app.state, 'db_monitor_task'):
                    app.state.db_monitor_task.cancel()
                    try:
                        await app.state.db_monitor_task
                    except asyncio.CancelledError:
                        pass
                    logger.info("Database monitor task stopped")

                # Stop task queue if it exists
                if hasattr(app.state, 'task_manager') and app.state.task_manager:
                    await app.state.task_manager.stop()
                    app_state["task_queue_running"] = False
                    logger.info("Task queue stopped")

                if hasattr(app.state, 'follow_scheduler'):
                    await app.state.follow_scheduler.stop()
                    app_state["follow_scheduler_running"] = False
                    logger.info("Follow scheduler stopped")
        except asyncio.TimeoutError:
            logger.warning("Services stop timed out")
        except Exception as e:
            logger.error(f"Error stopping services: {e}")

        # Create final backup and close database
        try:
            logger.info("Creating final backup before shutdown...")
            await db_manager.cleanup()
            app_state["db_connected"] = False
            logger.info("Database backup created and connections closed")
            
            # Close Redis connection with persistence
            if hasattr(app.state, 'redis_pool'):
                try:
                    redis_client = redis.Redis(connection_pool=app.state.redis_pool)
                    await redis_client.bgsave()  # Trigger background save
                    await redis_client.save()    # Wait for save to complete
                    await app.state.redis_pool.disconnect()
                    logger.info("Redis state saved and connection closed")
                except Exception as e:
                    logger.error(f"Error closing Redis connection: {e}")
        except Exception as e:
            logger.error(f"Error during final backup and cleanup: {e}")

        logger.info("Application shutdown complete")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "status_code": exc.status_code
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions."""
    error_msg = str(exc)
    logger.error(f"Unhandled exception: {error_msg}", exc_info=True)
    
    # If it's an HTTPException that was re-raised, preserve its status code and detail
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail or error_msg,
                "status_code": exc.status_code
            }
        )
    
    # For other exceptions, return 500 with the actual error message
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": error_msg,
            "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR
        }
    )

@app.get("/", tags=["health"])
async def root():
    """Root endpoint with basic application info."""
    return {
        "app": "Xauto API",
        "version": "0.2.0",
        "status": "healthy" if app_state["is_healthy"] else "unhealthy",
        "uptime": str(datetime.utcnow() - app_state["startup_time"]) if app_state["startup_time"] else None
    }

@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint."""
    if not app_state["is_healthy"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application is not healthy"
        )
    
    db_stats = db_manager.get_stats()
    return {
        "status": "healthy",
        "database": {
            "connected": app_state["db_connected"],
            "type": db_stats["type"],
            "errors": db_stats["errors"],
            "last_backup": db_stats["last_backup"]
        },
        "task_queue": "running" if app_state["task_queue_running"] else "stopped",
        "uptime": str(datetime.utcnow() - app_state["startup_time"]) if app_state["startup_time"] else None,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/health/database", tags=["health"])
async def database_health_check():
    """Check database health and connection"""
    try:
        async with db_manager.async_session() as session:
            # Try a simple query
            result = await session.execute(select(Account).limit(1))
            account = result.scalar_one_or_none()
            
            return {
                "status": "healthy",
                "database": {
                    "connected": db_manager.is_connected,
                    "type": db_manager.db_type,
                    "has_data": account is not None
                }
            }
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error: {str(e)}"
        )

@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    """Ensure database connection is available"""
    if not db_manager.is_connected:
        try:
            await db_manager.initialize()
        except Exception as e:
            logger.error(f"Database connection failed: {str(e)}")
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"detail": "Database connection not available"}
            )
    
    response = await call_next(request)
    return response

def main():
    """Entry point for the application."""
    try:
        # Configure uvicorn logging
        log_config = uvicorn.config.LOGGING_CONFIG
        log_config["formatters"]["access"]["fmt"] = "%(asctime)s - %(levelname)s - [%(name)s] - %(message)s"
        log_config["formatters"]["default"]["fmt"] = "%(asctime)s - %(levelname)s - [%(name)s] - %(message)s"
        
        # Reduce noise from access logs
        log_config["loggers"]["uvicorn.access"]["level"] = "WARNING"
        log_config["loggers"]["uvicorn.error"]["level"] = "WARNING"
        
        # Run server with custom logging
        uvicorn.run(
            "backend.app.main:app",
            host="0.0.0.0",
            port=9000,
            reload=True,
            log_level="warning",  # Only show warnings and errors
            log_config=log_config,
            workers=1  # Single worker for development
        )
    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
