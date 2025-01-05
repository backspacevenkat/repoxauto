from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base

class RateLimit(Base):
    __tablename__ = "rate_limits"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), index=True)
    endpoint = Column(String, index=True)  # e.g., 'user_profile', 'user_tweets'
    window = Column(String)  # '15min' or '24h'
    requests_count = Column(Integer, default=0)
    reset_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    account = relationship("Account", back_populates="rate_limits")

    def __repr__(self):
        return f"<RateLimit {self.account_id}: {self.endpoint} - {self.window}>"

    @property
    def is_expired(self) -> bool:
        """Check if rate limit window has expired"""
        if not self.reset_at:
            return True
        return datetime.utcnow() > self.reset_at

    def reset_if_expired(self):
        """Reset counter if window has expired"""
        if self.is_expired:
            self.requests_count = 0
            if self.window == '15min':
                self.reset_at = datetime.utcnow().replace(
                    minute=(datetime.utcnow().minute // 15) * 15,
                    second=0,
                    microsecond=0
                )
            else:  # 24h
                self.reset_at = datetime.utcnow().replace(
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0
                )
