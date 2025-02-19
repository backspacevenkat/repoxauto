from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime

class ProfileUpdateBase(BaseModel):
    account_no: str
    name: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    location: Optional[str] = None
    profile_image_path: Optional[str] = None
    profile_banner_path: Optional[str] = None
    lang: Optional[str] = None
    new_login: Optional[str] = None  # New field for username update

class ProfileUpdateCreate(ProfileUpdateBase):
    pass

class ProfileUpdateResponse(BaseModel):
    id: str
    account_no: str
    name: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    location: Optional[str] = None
    profile_image: Optional[str] = Field(None, alias='profile_image_path')  # Map from database field
    profile_banner: Optional[str] = Field(None, alias='profile_banner_path')  # Map from database field
    lang: Optional[str] = None
    new_login: Optional[str] = None  # New field for username update
    status: str
    new_auth_token: Optional[str] = None
    new_ct0: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    meta_data: Optional[dict] = None

    class Config:
        from_attributes = True
        populate_by_name = True  # Allow both alias and field name
        json_schema_extra = {
            'properties': {
                'profile_image': {
                    'description': 'Profile image path (mapped from profile_image_path)'
                },
                'profile_banner': {
                    'description': 'Profile banner path (mapped from profile_banner_path)'
                }
            }
        }

class ProfileUpdateBulkResponse(BaseModel):
    success: bool
    message: str
    updates: list[ProfileUpdateResponse]
    errors: Optional[list[dict]] = None

class ProfileUpdateCSVRow(BaseModel):
    account_no: str
    name: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    location: Optional[str] = None
    profile_image: Optional[str] = None  # Path to profile image
    profile_banner: Optional[str] = None  # Path to profile banner
    lang: Optional[str] = None
    new_login: Optional[str] = None  # New field for username update

    @classmethod
    def from_csv_row(cls, row: dict):
        """Create instance from CSV row, filtering out empty values"""
        filtered_data = {
            k: v.strip() 
            for k, v in row.items() 
            if v and v.strip()
        }
        return cls(**filtered_data)
