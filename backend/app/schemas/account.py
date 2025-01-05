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
    account_no: str = Field(..., description="Unique account identifier")
    act_type: Optional[AccountType] = Field(default=AccountType.NORMAL)
    login: str = Field(..., description="Twitter username/login")
    password: Optional[str] = None
    email: Optional[str] = None
    email_password: Optional[str] = None
    auth_token: str = Field(..., description="Twitter auth token")
    ct0: str = Field(..., description="Twitter ct0 token")
    two_fa: Optional[str] = None
    proxy_url: str = Field(..., description="Proxy server URL")
    proxy_port: str = Field(..., description="Proxy server port")
    proxy_username: str = Field(..., description="Proxy authentication username")
    proxy_password: str = Field(..., description="Proxy authentication password")
    user_agent: Optional[str] = Field(
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    consumer_key: Optional[str] = None
    consumer_secret: Optional[str] = None
    bearer_token: Optional[str] = None
    access_token: Optional[str] = None
    access_token_secret: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    language_status: Optional[str] = None
    developer_status: Optional[str] = None
    unlock_status: Optional[str] = None
    last_validation: Optional[str] = None
    last_validation_time: Optional[datetime] = None
    validation_in_progress: Optional[ValidationState] = Field(default=ValidationState.PENDING)
    recovery_attempts: int = Field(default=0, description="Number of recovery attempts made")
    last_recovery_time: Optional[datetime] = None
    recovery_status: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    @field_validator('proxy_port')
    @classmethod
    def validate_proxy_port(cls, v: str) -> str:
        if v is not None:
            # Convert to string if it's a number
            v = str(v)
            # Remove any decimal points and convert to integer
            if '.' in v:
                v = str(int(float(v)))
        return v

    @field_validator('proxy_password')
    @classmethod
    def validate_proxy_password(cls, v: str) -> str:
        """URL encode proxy password to handle special characters."""
        if v and v.strip():
            # URL encode the password, preserving special characters
            return quote_plus(v.strip())
        raise ValueError('proxy_password is required and cannot be empty')

    @field_validator('auth_token', 'ct0', 'proxy_url', 'proxy_username')
    @classmethod
    def validate_required_fields(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f'{info.field_name} is required and cannot be empty')
        return v.strip()

    def get_proxy_url(self) -> str:
        """Get properly formatted proxy URL with encoded credentials."""
        username = quote_plus(self.proxy_username)
        password = self.proxy_password  # Already URL encoded by validator
        return f"http://{username}:{password}@{self.proxy_url}:{self.proxy_port}"

    class Config:
        from_attributes = True

class AccountCreate(AccountBase):
    pass

class Account(AccountBase):
    id: int

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
    errors: List[str] = Field(default_factory=list)

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
