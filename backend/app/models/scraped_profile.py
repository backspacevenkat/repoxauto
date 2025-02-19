from backend.app.database import Base
from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime

class ScrapedProfile(Base):
    __tablename__ = 'scraped_profiles'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, index=True, nullable=False)
    screen_name = Column(String, nullable=True)
    name = Column(String, nullable=True)
    description = Column(String, nullable=True)
    location = Column(String, nullable=True)
    url = Column(String, nullable=True)
    profile_image_url = Column(String, nullable=True)
    profile_banner_url = Column(String, nullable=True)
    followers_count = Column(Integer, nullable=True)
    following_count = Column(Integer, nullable=True)
    tweets_count = Column(Integer, nullable=True)
    likes_count = Column(Integer, nullable=True)
    media_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
