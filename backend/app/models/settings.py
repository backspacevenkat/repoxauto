from sqlalchemy import Column, Integer, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class SystemSettings(Base):
    __tablename__ = "system_settings"
    
    id = Column(Integer, primary_key=True)
    max_concurrent_workers = Column(Integer, default=12)
    max_requests_per_worker = Column(Integer, default=900)
    request_interval = Column(Integer, default=60)
    _updated_at = Column("updated_at", DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def updated_at(self):
        return self._updated_at
