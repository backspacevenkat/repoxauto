import os
import sys
import uvicorn

def main():
    # Add the project root to Python path
    project_root = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(project_root)
    
    # Run the FastAPI application
    uvicorn.run(
        "backend.app.main:app",
        host="0.0.0.0",
        port=9000,
        reload=True,
        log_level="info",
        access_log=True,
        workers=1  # Single worker for development
    )

if __name__ == "__main__":
    main()
