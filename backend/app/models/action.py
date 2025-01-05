from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Text, UniqueConstraint, Index
from sqlalchemy.orm import relationship, validates
from sqlalchemy.sql import text
from datetime import datetime

from ..database import Base

class Action(Base):
    """Model for storing Twitter actions (like, retweet, etc.)"""
    __tablename__ = "actions"
    # Note: Indexes are created via migration to support SQLite's partial unique index
    # - uq_account_action_tweet: Unique index on (account_id, action_type, tweet_id) WHERE status IN ('pending', 'running', 'locked')
    # - idx_action_status: Index on status
    # - idx_account_action_created: Index on (account_id, action_type, created_at)

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"))
    task_id = Column(Integer, ForeignKey("tasks.id"))
    
    # Valid values for validation
    VALID_ACTION_TYPES = ['like_tweet', 'retweet_tweet', 'reply_tweet', 'quote_tweet', 'create_tweet']
    VALID_STATUSES = ['pending', 'running', 'completed', 'failed', 'cancelled', 'locked']
    VALID_API_METHODS = ['graphql', 'rest']
    
    # Action details
    action_type = Column(String, nullable=False)  # like_tweet, retweet_tweet, etc.
    api_method = Column(String, nullable=False, default='graphql')  # graphql or rest
    tweet_url = Column(String, nullable=True)  # Nullable for non-tweet actions like profile scraping
    tweet_id = Column(String)  # Extracted from URL
    status = Column(String, default="pending")  # pending, completed, failed
    error_message = Column(Text)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    executed_at = Column(DateTime)
    
    # Rate limiting
    rate_limit_reset = Column(DateTime)
    rate_limit_remaining = Column(Integer)
    
    # Additional data
    meta_data = Column(JSON)  # Store additional info like text_content for future actions
    
    # Relationships
    account = relationship("Account", back_populates="actions")
    task = relationship("Task", back_populates="actions")

    def __repr__(self):
        return f"<Action {self.id}: {self.action_type} by {self.account_id} on {self.tweet_url}>"

    @validates('action_type')
    def validate_action_type(self, key, value):
        if value not in self.VALID_ACTION_TYPES:
            raise ValueError(f"Invalid action type. Must be one of: {', '.join(self.VALID_ACTION_TYPES)}")
        return value
    
    @validates('status')
    def validate_status(self, key, value):
        if value not in self.VALID_STATUSES:
            raise ValueError(f"Invalid status. Must be one of: {', '.join(self.VALID_STATUSES)}")
        return value

    @validates('api_method')
    def validate_api_method(self, key, value):
        if value not in self.VALID_API_METHODS:
            raise ValueError(f"Invalid API method. Must be one of: {', '.join(self.VALID_API_METHODS)}")
        return value
