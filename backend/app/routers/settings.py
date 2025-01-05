from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional
import json
import os

router = APIRouter()

class Settings(BaseModel):
    maxWorkers: int
    requestsPerWorker: int
    requestInterval: int

SETTINGS_FILE = "settings.json"

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    return {
        "maxWorkers": 6,
        "requestsPerWorker": 900,
        "requestInterval": 15
    }

def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f)

@router.get("/settings")
async def get_settings():
    """Get current task queue settings"""
    try:
        return load_settings()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load settings: {str(e)}"
        )

@router.post("/settings")
async def update_settings(settings: Settings):
    """Update task queue settings"""
    try:
        if settings.maxWorkers < 1 or settings.maxWorkers > 12:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Max workers must be between 1 and 12"
            )
        
        if settings.requestsPerWorker < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Requests per worker must be positive"
            )
            
        if settings.requestInterval < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request interval must be positive"
            )
            
        save_settings(settings.dict())
        return {"message": "Settings updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update settings: {str(e)}"
        )
