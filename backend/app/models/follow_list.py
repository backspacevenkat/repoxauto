from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Enum, TypeDecorator
import json
from datetime import datetime

class JSONString(TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value)
        return None

    def process_result_value(self, value, dialect):
        if value is not None:
            return json.loads(value)
        return {}

from sqlalchemy.orm import relationship
import enum
from ..database import Base

class ListType(str, enum.Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"

class FollowList(Base):
    __tablename__ = "follow_lists"

    id = Column(Integer, primary_key=True)
    list_type = Column(Enum(ListType), nullable=False)
    username = Column(String, nullable=False, index=True, comment="Twitter username to follow")
    account_login = Column(String, ForeignKey("accounts.login"), nullable=True)  # Only for internal lists
    uploaded_by = Column(Integer, nullable=False)  # User ID who uploaded
    status = Column(String, default="pending", nullable=False)  # pending, processing, completed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    validated_at = Column(DateTime, nullable=True)
    meta_data = Column(JSONString, default="{}")

    # Relationships
    account = relationship("Account", foreign_keys=[account_login], backref="follow_lists")

class FollowProgress(Base):
    __tablename__ = "follow_progress"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id"))
    follow_list_id = Column(Integer, ForeignKey("follow_lists.id"))
    status = Column(String, default="pending")  # pending, in_progress, completed, failed
    started_at = Column(DateTime, nullable=True)  # When follow attempt started
    followed_at = Column(DateTime, nullable=True)  # When follow completed
    scheduled_for = Column(DateTime, nullable=True)  # When follow is scheduled to happen
    error_message = Column(String, nullable=True)
    meta_data = Column(JSONString, default="{}", nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    account = relationship("Account", back_populates="follow_progress")
    follow_list = relationship("FollowList")
