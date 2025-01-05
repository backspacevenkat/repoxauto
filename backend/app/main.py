from fastapi import FastAPI, HTTPException, status, WebSocket, WebSocketDisconnect
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

from .database import init_db, engine
from .routers import accounts, tasks, settings, search, actions
from .services.task_queue import TaskQueue
from .database import get_session

# Configure logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Xauto API",
    description="Twitter Account Management and Automation System",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    redirect_slashes=False
)

# Configure CORS
origins = [
    "http://localhost:3003",     # Frontend development server
    "http://localhost:3000",     # Alternative frontend port
    "http://localhost:9000",     # Backend server
    "ws://localhost:3003",       # WebSocket frontend development server
    "ws://localhost:3000",       # WebSocket alternative frontend port
    "ws://localhost:9000",       # WebSocket backend server
    "http://127.0.0.1:3003",    # Local frontend alternative
    "http://127.0.0.1:3000",    # Local frontend alternative
    "http://127.0.0.1:9000",    # Local backend alternative
    "ws://127.0.0.1:3003",      # Local WebSocket alternative
    "ws://127.0.0.1:3000",      # Local WebSocket alternative
    "ws://127.0.0.1:9000",      # Local WebSocket backend alternative
    "*"                         # Allow all origins in development
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
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

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        client_id = f"{websocket.client.host}:{websocket.client.port}"
        
        async with self._lock:
            # If client already has a connection, close it
            if client_id in self.active_connections:
                try:
                    old_ws = self.active_connections[client_id]
                    await old_ws.close(code=1000, reason="New connection from same client")
                    del self.active_connections[client_id]
                except Exception as e:
                    logger.error(f"Error closing existing connection for {client_id}: {e}")

            # Accept new connection
            try:
                await websocket.accept()
                self.active_connections[client_id] = websocket
                logger.info(f"New WebSocket connection from {client_id}. Total connections: {len(self.active_connections)}")
                
                # Send connection confirmation
                await websocket.send_json({
                    "type": "connection_status",
                    "status": "connected",
                    "client_id": client_id,
                    "timestamp": datetime.utcnow().isoformat()
                })
            except Exception as e:
                logger.error(f"Error in connection setup for {client_id}: {e}")
                if client_id in self.active_connections:
                    del self.active_connections[client_id]
                raise

    async def disconnect(self, websocket: WebSocket):
        client_id = f"{websocket.client.host}:{websocket.client.port}"
        async with self._lock:
            if client_id in self.active_connections:
                del self.active_connections[client_id]
                logger.info(f"WebSocket disconnected for {client_id}. Remaining connections: {len(self.active_connections)}")
                try:
                    await self.cleanup_connection(websocket)
                except Exception as e:
                    logger.error(f"Error cleaning up connection for {client_id}: {e}")

    async def cleanup_connection(self, websocket: WebSocket):
        """Clean up any resources associated with a disconnected WebSocket."""
        try:
            # Add any necessary cleanup here
            pass
        except Exception as e:
            logger.error(f"Error in cleanup: {e}")

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients."""
        if "timestamp" not in message:
            message["timestamp"] = datetime.utcnow().isoformat()
            
        async with self._lock:
            disconnected_clients = []
            for client_id, connection in self.active_connections.items():
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to client {client_id}: {e}")
                    disconnected_clients.append(client_id)
            
            # Clean up disconnected connections
            for client_id in disconnected_clients:
                if client_id in self.active_connections:
                    del self.active_connections[client_id]
                    logger.info(f"Removed disconnected client {client_id}")

manager = ConnectionManager()

# Make ConnectionManager available to routers
app.state.connection_manager = manager

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    last_heartbeat = datetime.utcnow()
    heartbeat_interval = 25  # seconds (match frontend interval)
    heartbeat_timeout = 35   # seconds (slightly longer than frontend interval)
    heartbeat_task = None
    
    async def check_heartbeat():
        """Check heartbeat in a separate task"""
        nonlocal last_heartbeat
        while True:
            try:
                await asyncio.sleep(heartbeat_timeout)
                if (datetime.utcnow() - last_heartbeat).total_seconds() > heartbeat_timeout:
                    logger.warning("Client missed heartbeat, closing connection")
                    try:
                        await websocket.send_json({
                            "type": "connection_error",
                            "message": "Missed heartbeat",
                            "timestamp": datetime.utcnow().isoformat()
                        })
                        await websocket.close(code=1000, reason="Missed heartbeat")
                    except Exception as e:
                        logger.error(f"Error closing connection: {e}")
                    break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat check: {e}")
                break
    
    try:
        await manager.connect(websocket)
        logger.info("New WebSocket connection established")
        
        # Start heartbeat check task
        heartbeat_task = asyncio.create_task(check_heartbeat())
        
        while True:
            try:
                # Wait for messages without timeout
                data = await websocket.receive_text()
                
                try:
                    message = json.loads(data)
                    message_type = message.get("type", "")
                    
                    if message_type == "heartbeat":
                        last_heartbeat = datetime.utcnow()
                        # Send heartbeat response
                        await websocket.send_json({
                            "type": "heartbeat_response",
                            "timestamp": datetime.utcnow().isoformat()
                        })
                        continue
                        
                except json.JSONDecodeError:
                    logger.warning("Received invalid JSON message")
                    continue
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    continue
                
                # Handle other message types if needed
                logger.debug(f"Received message: {data}")
                
            except WebSocketDisconnect:
                logger.info("WebSocket client disconnected normally")
                break
                
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                try:
                    await websocket.send_json({
                        "type": "connection_error",
                        "message": str(e),
                        "timestamp": datetime.utcnow().isoformat()
                    })
                except:
                    pass
                break
                
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
        
    finally:
        # Always ensure we clean up
        try:
            # Cancel heartbeat check task if it exists
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
                
            # Disconnect from manager
            await manager.disconnect(websocket)
                
        except Exception as e:
            logger.error(f"Error in connection cleanup: {e}")

async def broadcast_message(message: dict):
    """Broadcast a message to all connected WebSocket clients"""
    try:
        message["timestamp"] = datetime.utcnow().isoformat()
        await manager.broadcast(message)
    except Exception as e:
        logger.error(f"Error broadcasting message: {e}")

# Include routers
app.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
app.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
app.include_router(settings.router, tags=["settings"])
app.include_router(search.router, tags=["search"])
app.include_router(actions.router, prefix="/actions", tags=["actions"])

# Create task queue instance
task_queue = TaskQueue(get_session)

# Application state
app_state = {
    "startup_time": None,
    "is_healthy": False,
    "db_connected": False,
    "task_queue_running": False
}

@app.on_event("startup")
async def startup_event():
    """Initialize application on startup."""
    try:
        # Initialize database
        await init_db()
        app_state["db_connected"] = True
        logger.info("Database initialized successfully")

        # Load settings
        from .routers.settings import load_settings
        settings = load_settings()
        logger.info(f"Loaded settings: {settings}")

        # Start task queue with settings
        await task_queue.start(
            max_workers=settings['maxWorkers'],
            requests_per_worker=settings['requestsPerWorker'],
            request_interval=settings['requestInterval']
        )
        app_state["task_queue_running"] = True
        logger.info("Task queue started successfully")

        # Set startup time
        app_state["startup_time"] = datetime.utcnow()
        app_state["is_healthy"] = True
        
        logger.info("Application started successfully")
    except Exception as e:
        logger.error(f"Failed to initialize application: {e}")
        app_state["is_healthy"] = False
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown."""
    try:
        # Mark app as unhealthy first
        app_state["is_healthy"] = False
        
        # Stop task queue with a timeout
        try:
            async with asyncio.timeout(5):  # 5 second timeout
                await task_queue.stop()
                app_state["task_queue_running"] = False
                logger.info("Task queue stopped")
        except asyncio.TimeoutError:
            logger.warning("Task queue stop timed out")
        except Exception as e:
            logger.error(f"Error stopping task queue: {e}")

        # Close database connection
        try:
            await engine.dispose()
            app_state["db_connected"] = False
            logger.info("Database connection closed")
        except Exception as e:
            logger.error(f"Error closing database connection: {e}")

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
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
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
    
    return {
        "status": "healthy",
        "database": "connected" if app_state["db_connected"] else "disconnected",
        "task_queue": "running" if app_state["task_queue_running"] else "stopped",
        "uptime": str(datetime.utcnow() - app_state["startup_time"]) if app_state["startup_time"] else None,
        "timestamp": datetime.utcnow().isoformat()
    }

def main():
    """Entry point for the application."""
    try:
        uvicorn.run(
            "backend.app.main:app",
            host="0.0.0.0",
            port=9000,
            reload=True,
            log_level="info",
            access_log=True,
            workers=1  # Single worker for development
        )
    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
