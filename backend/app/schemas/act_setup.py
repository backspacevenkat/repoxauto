from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

class ActSetupStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class ActSetupBase(BaseModel):
    account_no: str
    source_file: Optional[str] = None
    threads: Optional[int] = Field(default=6, ge=1, le=12)
    status: ActSetupStatus = ActSetupStatus.PENDING
    error_message: Optional[str] = None
    last_attempt: Optional[datetime] = None
    retry_count: Optional[int] = Field(default=0, ge=0)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class ActSetupCreate(ActSetupBase):
    pass

class ActSetupUpdate(BaseModel):
    source_file: Optional[str] = None
    threads: Optional[int] = Field(ge=1, le=12)
    status: Optional[ActSetupStatus] = None
    error_message: Optional[str] = None
    last_attempt: Optional[datetime] = None
    retry_count: Optional[int] = Field(ge=0)

class ActSetup(ActSetupBase):
    id: int

    class Config:
        orm_mode = True

class ActSetupResponse(BaseModel):
    success: bool
    message: str
    data: Optional[ActSetup] = None

class BulkActSetupResponse(BaseModel):
    total: int
    successful: int
    failed: int
    errors: List[str]
