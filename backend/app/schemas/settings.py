from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict

class SystemSettingsBase(BaseModel):
    max_concurrent_workers: int = Field(default=12, ge=1, le=100)
    max_requests_per_worker: int = Field(default=900, ge=1, le=1000)
    request_interval: int = Field(default=60, ge=1, le=3600)

class SystemSettingsCreate(SystemSettingsBase):
    pass

class SystemSettingsUpdate(SystemSettingsBase):
    pass

class SystemSettingsResponse(SystemSettingsBase):
    id: int
    updated_at: datetime

    class Config:
        from_attributes = True

class WorkerUtilization(BaseModel):
    assigned_tasks: int
    completed_tasks: int
    is_active: bool
    health_status: str
    rate_limit_status: Dict[str, Optional[str | int | float]]

class WorkerStatus(BaseModel):
    total_workers: int
    active_workers: int
    tasks_completed: int
    tasks_pending: int
    worker_utilization: Dict[str, WorkerUtilization]
