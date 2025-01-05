from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List, ForwardRef
from datetime import datetime
from enum import Enum

class TaskType(str, Enum):
    # Search and scraping tasks
    SCRAPE_PROFILE = "scrape_profile"
    SCRAPE_TWEETS = "scrape_tweets"
    SEARCH_TRENDING = "search_trending"
    SEARCH_TWEETS = "search_tweets"
    SEARCH_USERS = "search_users"
    BATCH_SEARCH = "batch_search"
    
    # Action tasks
    LIKE_TWEET = "like_tweet"
    RETWEET = "retweet_tweet" 
    REPLY = "reply_tweet"
    QUOTE = "quote_tweet"
    CREATE = "create_tweet"

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class WorkerAccount(BaseModel):
    id: int
    account_no: str
    login: str
    proxy_url: Optional[str]
    last_validation_time: Optional[datetime]

    class Config:
        from_attributes = True

class TaskBase(BaseModel):
    type: TaskType
    input_params: Dict[str, Any]
    priority: Optional[int] = Field(default=0, ge=0, le=10)

    @validator('input_params')
    def validate_input_params(cls, v, values):
        task_type = values.get('type')
        
        # Skip validation for trending search since it doesn't need params
        if task_type == TaskType.SEARCH_TRENDING:
            return v
            
        # Validate action tasks
        if task_type in [TaskType.LIKE_TWEET, TaskType.RETWEET, TaskType.REPLY, TaskType.QUOTE, TaskType.CREATE]:
            if task_type != TaskType.CREATE and ('tweet_id' not in v or not v['tweet_id']):
                raise ValueError("Tweet ID is required for tweet interaction tasks")
                
            if task_type in [TaskType.REPLY, TaskType.QUOTE, TaskType.CREATE]:
                meta_data = v.get('meta_data', {})
                if not meta_data or 'text_content' not in meta_data or not meta_data['text_content']:
                    raise ValueError(f"{task_type} requires text content in meta_data")
            
            return v
            
        # Validate scraping tasks
        elif task_type in [TaskType.SCRAPE_PROFILE, TaskType.SCRAPE_TWEETS]:
            if 'username' not in v or not v['username']:
                raise ValueError("Username is required in input_params")
            
            if task_type == TaskType.SCRAPE_TWEETS:
                count = v.get('count', 15)
                hours = v.get('hours', 24)
                max_replies = v.get('max_replies', 7)
                if not isinstance(count, int) or count < 1 or count > 100:
                    raise ValueError("Tweet count must be between 1 and 100")
                if not isinstance(hours, int) or hours < 1 or hours > 168:  # Max 1 week
                    raise ValueError("Hours must be between 1 and 168")
                if not isinstance(max_replies, int) or max_replies < 0 or max_replies > 20:
                    raise ValueError("Max replies must be between 0 and 20")
        
        # Validate search tasks
        elif task_type in [TaskType.SEARCH_TWEETS, TaskType.SEARCH_USERS]:
            if 'keyword' not in v or not v['keyword']:
                raise ValueError("Keyword is required in input_params")
            
            count = v.get('count', 20)
            if not isinstance(count, int) or count < 1 or count > 100:
                raise ValueError("Search count must be between 1 and 100")
        
        # Validate batch search task
        elif task_type == TaskType.BATCH_SEARCH:
            if 'keywords' not in v or not v['keywords']:
                raise ValueError("Keywords list is required in input_params")
            if not isinstance(v['keywords'], list):
                raise ValueError("Keywords must be a list")
            if not all(isinstance(k, str) and k.strip() for k in v['keywords']):
                raise ValueError("All keywords must be non-empty strings")
            
            count = v.get('count_per_keyword', 20)
            if not isinstance(count, int) or count < 1 or count > 100:
                raise ValueError("Count per keyword must be between 1 and 100")

        return v

class TaskCreate(TaskBase):
    pass

class TaskUpdate(BaseModel):
    status: Optional[TaskStatus]
    result: Optional[Dict[str, Any]]
    error: Optional[str]

class TaskRead(TaskBase):
    id: int
    status: TaskStatus
    result: Optional[Dict[str, Any]]
    error: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    worker_account: Optional[WorkerAccount]
    retry_count: int
    execution_time: Optional[float] = None  # in seconds

    @validator('execution_time', pre=True, always=True)
    def calculate_execution_time(cls, v, values):
        if values.get('started_at') and values.get('completed_at'):
            return (values['completed_at'] - values['started_at']).total_seconds()
        return None

    class Config:
        from_attributes = True

class TaskBulkCreate(BaseModel):
    task_type: TaskType
    usernames: list[str]
    count: Optional[int] = Field(default=15, ge=1, le=100)
    hours: Optional[int] = Field(default=24, ge=1, le=168)  # Max 1 week
    max_replies: Optional[int] = Field(default=7, ge=0, le=20)  # Max replies per tweet
    priority: Optional[int] = Field(default=0, ge=0, le=10)

    @validator('usernames')
    def validate_usernames(cls, v):
        if not v:
            raise ValueError("Usernames list cannot be empty")
        if len(v) > 1000:
            raise ValueError("Maximum 1000 usernames allowed per bulk request")
        if not all(username.strip() for username in v):
            raise ValueError("All usernames must be non-empty")
        return [username.strip() for username in v]

class TaskBulkResponse(BaseModel):
    message: str
    task_ids: list[int]

class TaskList(BaseModel):
    tasks: List[Dict[str, Any]]
    total: int
    page: int
    page_size: int
    total_pages: int

    class Config:
        from_attributes = True

class TaskStats(BaseModel):
    total_tasks: int
    pending_tasks: int
    running_tasks: int
    completed_tasks: int
    failed_tasks: int
    average_completion_time: Optional[float]  # in seconds
    success_rate: float  # percentage
    total_workers: int
    active_workers: int
    rate_limited_workers: Optional[int]
    tasks_per_minute: Optional[float]
    estimated_completion_time: Optional[float]  # in minutes

    @validator('estimated_completion_time', pre=True, always=True)
    def calculate_estimated_completion(cls, v, values):
        if (values.get('pending_tasks') and values.get('tasks_per_minute') and 
            values['tasks_per_minute'] > 0):
            return values['pending_tasks'] / values['tasks_per_minute']
        return None

    class Config:
        from_attributes = True

class TaskError(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]]

# Create forward refs for circular references
TweetDataRef = ForwardRef('TweetData')
ReplyDataRef = ForwardRef('ReplyData')

class TaskResult(BaseModel):
    class ProfileData(BaseModel):
        username: str
        bio: Optional[str]
        profile_url: str
        profile_image_url: Optional[str]
        followers_count: Optional[int]
        following_count: Optional[int]
        tweets_count: Optional[int]
        created_at: Optional[datetime]

    class ReplyData(BaseModel):
        type: str  # 'reply' or 'thread'
        tweet: Optional[TweetDataRef]  # For single replies
        tweets: Optional[List[TweetDataRef]]  # For threads

    class TweetData(BaseModel):
        id: str
        text: str
        created_at: datetime
        author: str
        tweet_url: str
        metrics: Dict[str, int]
        media: Optional[List[Dict[str, Any]]]
        urls: Optional[List[Dict[str, str]]]
        replies: Optional[List[ReplyDataRef]]
        quoted_tweet: Optional[TweetDataRef]
        retweeted_by: Optional[str]
        retweeted_at: Optional[str]

    username: str
    profile_data: Optional[ProfileData]
    tweets: Optional[List[TweetDataRef]]
    collected_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True

# Update forward references
TaskResult.TweetData.model_rebuild()
TaskResult.ReplyData.model_rebuild()
