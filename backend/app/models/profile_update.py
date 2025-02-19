from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.types import JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..database import Base

class ProfileUpdate(Base):
    __tablename__ = "profile_updates"

    id = Column(String, primary_key=True)
    account_no = Column(String, ForeignKey('accounts.account_no', ondelete='CASCADE'), nullable=False, index=True)
    name = Column(String, nullable=True)
    description = Column(String, nullable=True)
    url = Column(String, nullable=True)
    location = Column(String, nullable=True)
    profile_image_path = Column(String, nullable=True)
    profile_banner_path = Column(String, nullable=True)
    lang = Column(String, nullable=True)
    new_login = Column(String, nullable=True)  # New field for username update
    status = Column(String, nullable=False, server_default='pending', index=True)
    meta_data = Column(JSON, nullable=True)
    # Fields to track credential updates
    new_auth_token = Column(String, nullable=True)
    new_ct0 = Column(String, nullable=True)
    error = Column(Text, nullable=True)  # To store any error messages
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    account = relationship("Account", back_populates="profile_updates")

    def __repr__(self):
        return f"<ProfileUpdate {self.id} for {self.account_no}>"

    def to_dict(self):
        """Convert profile update to dictionary"""
        return {
            "id": self.id,
            "account_no": self.account_no,
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "location": self.location,
            "profile_image_path": self.profile_image_path,
            "profile_banner_path": self.profile_banner_path,
            "lang": self.lang,
            "new_login": self.new_login,
            "status": self.status,
            "metadata": self.meta_data,
            "new_auth_token": self.new_auth_token,
            "new_ct0": self.new_ct0,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
