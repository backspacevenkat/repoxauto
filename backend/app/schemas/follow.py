from pydantic import BaseModel
from typing import Optional, Dict, List
from datetime import datetime
from enum import Enum

class ListType(str, Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"

from pydantic import Field, validator
from typing import Optional, Dict, List, Any

class FollowSettingsBase(BaseModel):
    max_follows_per_interval: int = Field(default=1, ge=1, description="Maximum follows per interval")
    interval_minutes: int = Field(default=16, ge=1, le=60, description="Minutes between follows")
    max_follows_per_day: int = Field(default=30, ge=1, le=100, description="Maximum follows per day")
    internal_ratio: int = Field(default=5, ge=0, description="Number of internal follows per day")
    external_ratio: int = Field(default=25, ge=0, description="Number of external follows per day")
    min_following: int = Field(default=300, ge=0, description="Minimum following count")
    max_following: int = Field(default=400, ge=0, description="Maximum following count")
    schedule_groups: int = Field(default=3, ge=1, le=24, description="Number of schedule groups")
    schedule_hours: int = Field(default=8, ge=1, le=24, description="Hours per schedule window")
    is_active: bool = Field(default=False, description="Whether follow system is running")
    meta_data: Optional[Dict[str, Any]] = Field(
        default_factory=lambda: {
            "last_start": None,
            "last_stop": None,
            "total_follows": 0,
            "successful_follows": 0,
            "failed_follows": 0,
            "system_health": "unknown"
        },
        description="Additional system metadata"
    )

    @validator('max_following')
    def validate_following_limits(cls, v, values):
        if 'min_following' in values and v < values['min_following']:
            raise ValueError('max_following must be greater than min_following')
        return v

    @validator('external_ratio', 'internal_ratio')
    def validate_ratios(cls, v, values):
        if 'max_follows_per_day' in values and v > values['max_follows_per_day']:
            raise ValueError('ratio cannot be greater than max_follows_per_day')
        return v

class FollowSettingsCreate(FollowSettingsBase):
    pass

class FollowSettings(FollowSettingsBase):
    id: int
    last_updated: Optional[datetime]

    model_config = {
        "from_attributes": True
    }

class FollowListBase(BaseModel):
    list_type: ListType
    username: str
    status: str = "pending"
    meta_data: Optional[Dict] = None

class FollowListCreate(FollowListBase):
    pass

class FollowList(FollowListBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {
        "from_attributes": True
    }

class FollowProgressBase(BaseModel):
    account_id: int
    follow_list_id: int
    status: str
    error_message: Optional[str]
    meta_data: Optional[Dict] = None

class FollowProgressCreate(FollowProgressBase):
    pass

class FollowProgress(FollowProgressBase):
    id: int
    followed_at: Optional[datetime]

    model_config = {
        "from_attributes": True
    }

class FollowStats(BaseModel):
    # Account statistics
    total_accounts: int = Field(description="Total number of accounts in system")
    accounts_following: int = Field(description="Number of accounts currently following")
    active_accounts: int = Field(default=0, description="Number of currently active accounts")
    rate_limited_accounts: int = Field(default=0, description="Number of rate limited accounts")
    
    # Follow list statistics
    total_internal: int = Field(description="Total internal usernames to follow")
    total_external: int = Field(description="Total external usernames to follow")
    pending_internal: int = Field(default=0, description="Pending internal follows")
    pending_external: int = Field(default=0, description="Pending external follows")
    
    # Follow progress
    follows_today: int = Field(description="Total follows completed today")
    follows_this_interval: int = Field(description="Follows completed in current interval")
    successful_follows: int = Field(default=0, description="Total successful follows")
    failed_follows: int = Field(default=0, description="Total failed follows")
    
    # Scheduler status
    active_group: Optional[int] = Field(description="Currently active schedule group")
    next_group_start: Optional[datetime] = Field(description="Next group start time")
    system_active_since: Optional[datetime] = Field(description="When system was last started")
    
    # Performance metrics
    average_success_rate: float = Field(default=0.0, description="Average follow success rate")
    average_follows_per_hour: float = Field(default=0.0, description="Average follows per hour")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "total_accounts": 100,
                "accounts_following": 50,
                "active_accounts": 30,
                "total_internal": 1000,
                "total_external": 5000,
                "follows_today": 150,
                "follows_this_interval": 5,
                "average_success_rate": 0.95,
                "average_follows_per_hour": 12.5
            }
        }
    }
