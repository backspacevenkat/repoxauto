from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base

class TrendingTopic(Base):
    __tablename__ = "trending_topics"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    tweet_volume = Column(Integer, nullable=True)
    domain = Column(String, nullable=True)
    meta_data = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    account_id = Column(Integer, ForeignKey("accounts.id"))

    # Relationships
    account = relationship("Account", back_populates="trending_topics")

    def to_dict(self):
        return {
            "name": self.name,
            "tweet_volume": self.tweet_volume,
            "domain": self.domain,
            "metadata": self.meta_data,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }

    def __repr__(self):
        return f"<TrendingTopic {self.name}>"

class TopicTweet(Base):
    __tablename__ = "topic_tweets"

    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String, index=True)
    tweet_id = Column(String, index=True)
    tweet_data = Column(JSON)
    timestamp = Column(DateTime, default=datetime.utcnow)
    account_id = Column(Integer, ForeignKey("accounts.id"))

    # Relationships
    account = relationship("Account", back_populates="topic_tweets")

    def to_dict(self):
        return {
            "keyword": self.keyword,
            "tweet_id": self.tweet_id,
            **self.tweet_data,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }

    def __repr__(self):
        return f"<TopicTweet {self.tweet_id}>"

class SearchedUser(Base):
    __tablename__ = "searched_users"

    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String, index=True)
    user_id = Column(String, index=True)
    user_data = Column(JSON)
    timestamp = Column(DateTime, default=datetime.utcnow)
    account_id = Column(Integer, ForeignKey("accounts.id"))

    # Relationships
    account = relationship("Account", back_populates="searched_users")

    def to_dict(self):
        return {
            "keyword": self.keyword,
            "user_id": self.user_id,
            **self.user_data,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }

    def __repr__(self):
        return f"<SearchedUser {self.user_id}>"
