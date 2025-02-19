from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SQLEnum, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base
from ..schemas.act_setup import ActSetupStatus

class ActSetup(Base):
    __tablename__ = "act_setups"

    id = Column(Integer, primary_key=True, index=True)
    account_no = Column(String, ForeignKey("accounts.account_no", ondelete="CASCADE"), nullable=False)
    source_file = Column(String, nullable=True)
    threads = Column(Integer, default=6)
    status = Column(SQLEnum(ActSetupStatus), default=ActSetupStatus.PENDING)
    error_message = Column(Text, nullable=True)
    last_attempt = Column(DateTime, nullable=True)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    account = relationship("Account", back_populates="act_setups")

    def to_dict(self):
        """Convert model instance to dictionary."""
        return {
            "id": self.id,
            "account_no": self.account_no,
            "source_file": self.source_file,
            "threads": self.threads,
            "status": self.status.value if self.status else None,
            "error_message": self.error_message,
            "last_attempt": self.last_attempt.isoformat() if self.last_attempt else None,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

    def update(self, data: dict):
        """Update model instance with dictionary data."""
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.updated_at = datetime.utcnow()
