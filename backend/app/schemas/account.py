from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from enum import Enum
from datetime import datetime
from urllib.parse import quote_plus

class AccountType(str, Enum):
    NORMAL = "normal"
    WORKER = "worker"

class ValidationState(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    VALIDATING = "validating"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"

class AccountBase(BaseModel):
    account_no: str
    login: str
    email: Optional[str] = None
    act_type: Optional[str] = None
    oauth_setup_status: Optional[str] = "PENDING"
    is_active: bool = True
    is_worker: bool = False

    class Config:
        from_attributes = True

class AccountResponse(AccountBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AccountCreate(AccountBase):
    class Config:
        from_attributes = True

class AccountValidation(BaseModel):
    status: str
    message: Optional[str] = None
    account_no: str
    validation_result: str

    class Config:
        from_attributes = True

class AccountImportResponse(BaseModel):
    total_imported: int
    successful: int
    failed: int
    errors: list[str]

class ValidationStatus(BaseModel):
    account_no: str
    status: str
    message: Optional[str] = None

class BulkValidationResponse(BaseModel):
    total: int
    in_progress: int
    completed: int
    statuses: List[ValidationStatus] = Field(default_factory=list)
    message: Optional[str] = None
