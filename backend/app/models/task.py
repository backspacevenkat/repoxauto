from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey, Float
from sqlalchemy.orm import relationship, validates
from datetime import datetime
from ..database import Base

class Task(Base):
    __tablename__ = "tasks"

    # Valid task types
    VALID_TASK_TYPES = [
        # Tweet interaction tasks
        'like_tweet', 'retweet_tweet', 'reply_tweet', 'quote_tweet', 'create_tweet',
        # Search and scraping tasks
        'scrape_profile', 'scrape_tweets', 'search_trending', 'search_tweets', 'search_users',
        'user_profile', 'user_tweets'
    ]

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, index=True)  # Task type from VALID_TASK_TYPES
    status = Column(String, index=True, default="pending")  # pending, running, completed, failed
    input_params = Column(JSON, nullable=False)
    result = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    worker_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    priority = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    execution_time = Column(Float, nullable=True)  # in seconds

    # Relationships
    worker_account = relationship(
        "Account",
        back_populates="tasks",
        foreign_keys=[worker_account_id]
    )
    actions = relationship(
        "Action",
        back_populates="task",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Task {self.id}: {self.type} - {self.status}>"

    @validates('type')
    def validate_type(self, key, value):
        """Validate task type"""
        if value not in self.VALID_TASK_TYPES:
            raise ValueError(f"Invalid task type. Must be one of: {', '.join(self.VALID_TASK_TYPES)}")
        return value

    def update_status(self, status: str):
        """Update task status and related timestamps"""
        self.status = status
        if status == "running":
            self.started_at = datetime.utcnow()
        elif status in ["completed", "failed"]:
            self.completed_at = datetime.utcnow()
            if self.started_at:
                self.execution_time = (self.completed_at - self.started_at).total_seconds()

    def to_dict(self):
        """Convert task to dictionary"""
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status,
            "input_params": self.input_params,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "worker_account_id": self.worker_account_id,
            "priority": self.priority,
            "retry_count": self.retry_count,
            "execution_time": self.execution_time,
            "worker_account": self.worker_account.to_dict() if self.worker_account else None
        }

    @property
    def username(self) -> str:
        """Get username from input params"""
        return self.input_params.get("username", "")

    @property
    def tweet_count(self) -> int:
        """Get tweet count from input params for tweet scraping tasks"""
        return self.input_params.get("count", 15) if self.type == "scrape_tweets" else None

    @property
    def is_completed(self) -> bool:
        """Check if task is completed"""
        return self.status == "completed"

    @property
    def is_failed(self) -> bool:
        """Check if task is failed"""
        return self.status == "failed"

    @property
    def is_running(self) -> bool:
        """Check if task is running"""
        return self.status == "running"

    @property
    def is_pending(self) -> bool:
        """Check if task is pending"""
        return self.status == "pending"

    @property
    def can_retry(self) -> bool:
        """Check if task can be retried"""
        return self.is_failed and self.retry_count < 3

    def format_result(self) -> dict:
        """Format task result for API response"""
        if not self.result:
            return None

        formatted = {
            "username": self.username,
            "collected_at": self.completed_at.isoformat() if self.completed_at else None
        }

        if self.type == "scrape_profile":
            profile_data = self.result.get("profile_data", {})
            formatted["profile_data"] = {
                "username": profile_data.get("username", self.username),
                "bio": profile_data.get("bio"),
                "profile_url": profile_data.get("profile_url"),
                "profile_image_url": profile_data.get("profile_image_url"),
                "followers_count": profile_data.get("followers_count"),
                "following_count": profile_data.get("following_count"),
                "tweets_count": profile_data.get("tweets_count"),
                "created_at": profile_data.get("created_at")
            }
        elif self.type == "scrape_tweets":
            tweets = self.result.get("tweets", [])
            formatted["tweets"] = [
                {
                    "id": tweet.get("id"),
                    "text": tweet.get("text"),
                    "created_at": tweet.get("created_at"),
                    "metrics": tweet.get("metrics", {}),
                    "media": tweet.get("media", []),
                    "urls": tweet.get("urls", [])
                }
                for tweet in tweets
            ]

        return formatted

    def format_error(self) -> dict:
        """Format task error for API response"""
        if not self.error:
            return None

        return {
            "code": "task_error",
            "message": self.error,
            "details": {
                "task_id": self.id,
                "type": self.type,
                "retry_count": self.retry_count
            }
        }
