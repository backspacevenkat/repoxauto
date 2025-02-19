from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean,
    Enum as SQLEnum, Index
)
from sqlalchemy import JSON
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

# Import Base from base.py instead of database
from .base import Base

class ValidationState(str, enum.Enum):
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class OAuthSetupState(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS" 
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NEEDS_SETUP = "NEEDS_SETUP"  # Added to handle legacy status

    @classmethod
    def _missing_(cls, value):
        """Handle missing/invalid enum values"""
        if isinstance(value, str):
            # Handle both formats of NEEDS_SETUP
            if value.replace(" ", "_").upper() == "NEEDS_SETUP":
                return cls.NEEDS_SETUP
            # Try to match by normalizing the string
            try:
                return cls[value.replace(" ", "_").upper()]
            except KeyError:
                pass
        # Map any unknown values to PENDING
        return cls.PENDING

class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    account_no = Column(String, unique=True, index=True, nullable=False, server_default='')
    act_type = Column(String, nullable=False, server_default='normal')  # 'normal' or 'worker'
    login = Column(String, nullable=False, server_default='', unique=True, index=True)
    password = Column(String, nullable=True)
    old_password = Column(String, nullable=True)  # Store previous password for fallback
    email = Column(String)
    email_password = Column(String)
    auth_token = Column(Text)
    ct0 = Column(Text)
    two_fa = Column(Text)
    proxy_url = Column(String)
    proxy_port = Column(String)
    proxy_username = Column(String)
    proxy_password = Column(String)
    user_agent = Column(Text)
    consumer_key = Column(Text)
    consumer_secret = Column(Text)
    bearer_token = Column(Text)
    access_token = Column(Text)
    access_token_secret = Column(Text)
    client_id = Column(Text)
    client_secret = Column(Text)
    language_status = Column(Text)
    developer_status = Column(Text)
    unlock_status = Column(Text)

    # Worker-specific fields
    is_active = Column(Boolean, default=True)
    is_worker = Column(Boolean, default=False)
    is_suspended = Column(Boolean, default=False)
    credentials_valid = Column(Boolean, default=True)
    following_count = Column(Integer, default=0, nullable=False)
    daily_follows = Column(Integer, default=0)
    total_follows = Column(Integer, default=0)
    failed_follow_attempts = Column(Integer, default=0)
    
    # Rate limiting
    rate_limit_until = Column(DateTime, nullable=True)
    current_15min_requests = Column(Integer, default=0)
    current_24h_requests = Column(Integer, default=0)
    last_rate_limit_reset = Column(DateTime, nullable=True)
    
    # Timestamps
    last_followed_at = Column(DateTime, nullable=True)
    last_login = Column(DateTime, nullable=True)
    activated_at = Column(DateTime, nullable=True)
    last_validation_time = Column(DateTime, nullable=True)
    last_task_time = Column(DateTime, nullable=True)
    
    # Task statistics
    total_tasks_completed = Column(Integer, default=0)
    total_tasks_failed = Column(Integer, default=0)
    
    # Validation and recovery fields
    validation_in_progress = Column(SQLEnum(ValidationState), default=ValidationState.PENDING)
    meta_data = Column(JSON, nullable=True, server_default='{}')
    last_validation = Column(Text)
    recovery_attempts = Column(Integer, default=0)
    recovery_status = Column(Text)
    last_recovery_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    # Make oauth_setup_status nullable during transition
    oauth_setup_status = Column(
        SQLEnum(OAuthSetupState), 
        nullable=True,  # Allow null during migration
        default=OAuthSetupState.PENDING
    )

    # Relationships
    tasks = relationship(
        "Task",
        back_populates="worker_account",
        foreign_keys="Task.worker_account_id"
    )
    actions = relationship(
        "Action",
        back_populates="account",
        cascade="all, delete-orphan"
    )
    rate_limits = relationship(
        "RateLimit",
        back_populates="account",
        cascade="all, delete-orphan"
    )
    trending_topics = relationship(
        "TrendingTopic",
        back_populates="account",
        cascade="all, delete-orphan"
    )
    topic_tweets = relationship(
        "TopicTweet",
        back_populates="account",
        cascade="all, delete-orphan"
    )
    searched_users = relationship(
        "SearchedUser",
        back_populates="account",
        cascade="all, delete-orphan"
    )
    profile_updates = relationship(
        "ProfileUpdate",  # Use string reference to avoid circular imports
        back_populates="account",
        cascade="all, delete-orphan"
    )
    follow_progress = relationship(
        "FollowProgress",
        back_populates="account",
        cascade="all, delete-orphan",
        lazy="selectin"  # Eager loading to avoid N+1 queries
    )

    def __repr__(self):
        return f"<Account {self.account_no}: {self.act_type}>"

    def to_dict(self):
        """Convert account to dictionary with all necessary fields"""
        return {
            "id": self.id,
            "account_no": self.account_no,
            "act_type": self.act_type,
            "login": self.login,
            "email": self.email,
            "email_password": self.email_password,
            "auth_token": self.auth_token,
            "ct0": self.ct0,
            "proxy_url": self.proxy_url,
            "proxy_port": self.proxy_port,
            "proxy_username": self.proxy_username,
            "proxy_password": self.proxy_password,
            "user_agent": self.user_agent,
            # OAuth credentials
            "consumer_key": self.consumer_key,
            "consumer_secret": self.consumer_secret,
            "bearer_token": self.bearer_token,
            "access_token": self.access_token,
            "access_token_secret": self.access_token_secret,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            # Worker status fields
            "is_active": self.is_active,
            "is_worker": self.is_worker,
            "credentials_valid": self.credentials_valid,
            "following_count": self.following_count,
            "daily_follows": self.daily_follows,
            "total_follows": self.total_follows,
            "failed_follow_attempts": self.failed_follow_attempts,
            "last_followed_at": self.last_followed_at.isoformat() if self.last_followed_at else None,
            
            # Task and validation fields
            "last_validation_time": self.last_validation_time.isoformat() if self.last_validation_time else None,
            "last_task_time": self.last_task_time.isoformat() if self.last_task_time else None,
            "total_tasks_completed": self.total_tasks_completed,
            "total_tasks_failed": self.total_tasks_failed,
            
            # Rate limiting fields
            "current_15min_requests": self.current_15min_requests,
            "current_24h_requests": self.current_24h_requests,
            "last_rate_limit_reset": self.last_rate_limit_reset.isoformat() if self.last_rate_limit_reset else None,
            "rate_limit_until": self.rate_limit_until.isoformat() if self.rate_limit_until else None,
            "validation_in_progress": self.validation_in_progress.value if self.validation_in_progress else None,
            "last_validation": self.last_validation,
            "recovery_attempts": self.recovery_attempts,
            "recovery_status": self.recovery_status,
            "last_recovery_time": self.last_recovery_time.isoformat() if self.last_recovery_time else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

    @property
    def is_worker_type(self) -> bool:
        """Check if account is a worker account"""
        return self.act_type == "worker"

    @property
    def is_rate_limited(self) -> bool:
        """Check if account is currently rate limited"""
        return (
            self.current_15min_requests >= 900 or  # Twitter's 15-min limit
            self.current_24h_requests >= 100000    # Twitter's 24h limit
        )

    @property
    def success_rate(self) -> float:
        """Calculate task success rate"""
        total = self.total_tasks_completed + self.total_tasks_failed
        if total == 0:
            return 0.0
        return (self.total_tasks_completed / total) * 100

    def update_task_stats(self, task_succeeded: bool):
        """Update task statistics"""
        if task_succeeded:
            self.total_tasks_completed += 1
        else:
            self.total_tasks_failed += 1
        self.last_task_time = datetime.utcnow()
        
    def update_follow_stats(self, follow_succeeded: bool):
        """Update follow statistics"""
        now = datetime.utcnow()
        self.last_followed_at = now
        
        if follow_succeeded:
            self.following_count += 1
            self.daily_follows += 1
            self.total_follows += 1
        else:
            self.failed_follow_attempts += 1
            
        # Reset daily follows at midnight UTC
        if self.last_followed_at and self.last_followed_at.date() < now.date():
            self.daily_follows = 0

    def can_follow_more(self, max_follows_per_day: int, max_following: int) -> bool:
        """Check if account can follow more users based on limits"""
        return (
            self.daily_follows < max_follows_per_day and
            self.following_count < max_following and
            self.failed_follow_attempts < 10  # Stop after 10 failed attempts
        )

    def increment_request_counter(self):
        """Increment request counters"""
        now = datetime.utcnow()
        
        # Reset counters if needed
        if self.last_rate_limit_reset:
            # Reset 15-min counter
            if (now - self.last_rate_limit_reset).total_seconds() > 900:  # 15 minutes
                self.current_15min_requests = 0
            
            # Reset 24h counter
            if (now - self.last_rate_limit_reset).total_seconds() > 86400:  # 24 hours
                self.current_24h_requests = 0

        self.current_15min_requests += 1
        self.current_24h_requests += 1
        self.last_rate_limit_reset = now

    def can_process_task(self) -> bool:
        """Check if account can process new tasks"""
        return (
            self.is_worker and
            self.is_active and
            self.credentials_valid and
            not self.is_rate_limited and
            self.auth_token and
            self.ct0 and
            self.validation_in_progress != ValidationState.VALIDATING and
            self.validation_in_progress != ValidationState.RECOVERING and
            (self.last_followed_at is None or
             (datetime.utcnow() - self.last_followed_at).total_seconds() > 60)  # Rate limit: 1 follow per minute
        )

    def get_proxy_config(self) -> dict:
        """Get proxy configuration"""
        if not all([self.proxy_url, self.proxy_port, self.proxy_username, self.proxy_password]):
            return None
        
        return {
            "proxy_url": self.proxy_url,
            "proxy_port": self.proxy_port,
            "proxy_username": self.proxy_username,
            "proxy_password": self.proxy_password
        }
