from datetime import datetime
from sqlalchemy import Boolean, Column, Integer, String, DateTime, JSON
from ..database import Base

class FollowSettings(Base):
    __tablename__ = "follow_settings"

    id = Column(Integer, primary_key=True, index=True)
    is_active = Column(Boolean, default=True)  # Controls if follow system is enabled
    
    # Follow limits
    max_follows_per_day = Column(Integer, default=30)
    max_follows_per_interval = Column(Integer, default=1)
    min_following = Column(Integer, default=300)  # Minimum following count before account can follow
    max_following = Column(Integer, default=400)  # Maximum following count before account is deactivated
    interval_minutes = Column(Integer, default=16)
    
    # Schedule settings
    schedule_groups = Column(Integer, default=3)  # Number of groups to split accounts into
    schedule_hours = Column(Integer, default=8)   # Hours per group
    
    # Distribution settings
    internal_ratio = Column(Integer, default=1)  # Internal follows per interval
    external_ratio = Column(Integer, default=1)  # External follows per interval
    
    # System state
    last_active = Column(DateTime, nullable=True)
    meta_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    class Config:
        from_attributes = True  # For Pydantic v2 compatibility
