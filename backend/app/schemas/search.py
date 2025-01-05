from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

# Base schemas for reading data
class TrendingTopicBase(BaseModel):
    name: str
    tweet_volume: Optional[int] = None
    domain: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class TopicTweetBase(BaseModel):
    keyword: str
    tweet_id: str
    tweet_data: Dict[str, Any]

class SearchedUserBase(BaseModel):
    keyword: str
    user_id: str
    user_data: Dict[str, Any]

# Schemas for creating new records
class TrendingTopicCreate(TrendingTopicBase):
    pass

class TopicTweetCreate(TopicTweetBase):
    pass

class SearchedUserCreate(SearchedUserBase):
    pass

# Schemas for reading records (includes DB fields)
class TrendingTopic(TrendingTopicBase):
    id: int
    account_id: int
    timestamp: datetime

    class Config:
        from_attributes = True

class TopicTweet(TopicTweetBase):
    id: int
    account_id: int
    timestamp: datetime

    class Config:
        orm_mode = True

class SearchedUser(SearchedUserBase):
    id: int
    account_id: int
    timestamp: datetime

    class Config:
        orm_mode = True

# Request schemas
class SearchRequest(BaseModel):
    keyword: str
    count: Optional[int] = 10
    cursor: Optional[str] = None

# Response schemas
class TrendingTopicsResponse(BaseModel):
    trends: List[TrendingTopic]
    timestamp: datetime

class TopicTweetsResponse(BaseModel):
    tweets: List[TopicTweet]
    next_cursor: Optional[str] = None
    keyword: str
    timestamp: datetime

class SearchedUsersResponse(BaseModel):
    users: List[SearchedUser]
    next_cursor: Optional[str] = None
    keyword: str
    timestamp: datetime

# Batch operation schemas
class BatchSearchRequest(BaseModel):
    keywords: List[str]
    count_per_keyword: Optional[int] = 10

class BatchSearchResponse(BaseModel):
    results: Dict[str, Any]
    timestamp: datetime
