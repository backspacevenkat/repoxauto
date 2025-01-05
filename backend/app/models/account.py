from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from ..database import Base

class ValidationState(str, enum.Enum):
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    account_no = Column(String, unique=True, index=True)
    act_type = Column(String)  # 'normal' or 'worker'
    login = Column(String)
    password = Column(String)
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
    last_validation_time = Column(DateTime, nullable=True)
    last_task_time = Column(DateTime, nullable=True)
    total_tasks_completed = Column(Integer, default=0)
    total_tasks_failed = Column(Integer, default=0)
    current_15min_requests = Column(Integer, default=0)
    current_24h_requests = Column(Integer, default=0)
    last_rate_limit_reset = Column(DateTime, nullable=True)

    # Validation and recovery fields
    validation_in_progress = Column(SQLEnum(ValidationState), default=ValidationState.PENDING)
    last_validation = Column(Text)
    recovery_attempts = Column(Integer, default=0)
    recovery_status = Column(Text)
    last_recovery_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

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

    def __repr__(self):
        return f"<Account {self.account_no}: {self.act_type}>"

    def to_dict(self):
        """Convert account to dictionary"""
        return {
            "id": self.id,
            "account_no": self.account_no,
            "act_type": self.act_type,
            "login": self.login,
            "proxy_url": self.proxy_url,
            "proxy_port": self.proxy_port,
            "is_active": self.is_active,
            "last_validation_time": self.last_validation_time.isoformat() if self.last_validation_time else None,
            "last_task_time": self.last_task_time.isoformat() if self.last_task_time else None,
            "total_tasks_completed": self.total_tasks_completed,
            "total_tasks_failed": self.total_tasks_failed,
            "current_15min_requests": self.current_15min_requests,
            "current_24h_requests": self.current_24h_requests,
            "last_rate_limit_reset": self.last_rate_limit_reset.isoformat() if self.last_rate_limit_reset else None,
            "validation_in_progress": self.validation_in_progress.value if self.validation_in_progress else None,
            "last_validation": self.last_validation,
            "recovery_attempts": self.recovery_attempts,
            "recovery_status": self.recovery_status,
            "last_recovery_time": self.last_recovery_time.isoformat() if self.last_recovery_time else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

    @property
    def is_worker(self) -> bool:
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
            not self.is_rate_limited and
            self.auth_token and
            self.ct0 and
            self.validation_in_progress != ValidationState.VALIDATING and
            self.validation_in_progress != ValidationState.RECOVERING
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
