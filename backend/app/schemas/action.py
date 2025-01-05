from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, Union, Literal
from datetime import datetime

# Define valid action types and methods
ActionType = Literal['like_tweet', 'retweet_tweet', 'reply_tweet', 'quote_tweet', 'create_tweet']
ActionStatus = Literal['pending', 'running', 'completed', 'failed', 'cancelled']
ApiMethod = Literal['graphql', 'rest']

class ActionMetadata(BaseModel):
    """Schema for action metadata"""
    text_content: Optional[str] = Field(None, description="Required for reply, quote, and create tweet actions")
    media: Optional[str] = Field(None, description="Optional media file path")
    priority: Optional[int] = Field(0, description="Action priority (higher = more priority)")
    queued_at: Optional[str] = None
    retry_of: Optional[int] = Field(None, description="ID of original action if this is a retry")
    retry_count: Optional[int] = Field(0, description="Number of times this action has been retried")
    next_attempt_after: Optional[str] = None

class ActionBase(BaseModel):
    action_type: ActionType
    tweet_url: str
    account_id: int
    api_method: ApiMethod = 'graphql'  # Default to GraphQL
    meta_data: Optional[ActionMetadata] = None

    @validator('action_type')
    def validate_action_type(cls, v, values):
        meta_data = values.get('meta_data', {})
        if meta_data and isinstance(meta_data, dict):
            text_content = meta_data.get('text_content')
            
            # Validate required text_content for certain action types
            if v in ['reply_tweet', 'quote_tweet', 'create_tweet'] and not text_content:
                raise ValueError(f"{v} requires text_content in metadata")
        
        return v

    @validator('tweet_url')
    def validate_tweet_url(cls, v, values):
        action_type = values.get('action_type')
        
        # create_tweet doesn't require a tweet URL
        if action_type == 'create_tweet' and v:
            raise ValueError("create_tweet action should not have a tweet_url")
        
        # other actions require a valid tweet URL
        if action_type != 'create_tweet' and not v:
            raise ValueError(f"{action_type} requires a valid tweet_url")
        
        if v and not ('twitter.com' in v or 'x.com' in v):
            raise ValueError("Invalid tweet URL format")
        
        return v

class ActionCreate(ActionBase):
    pass

class ActionUpdate(BaseModel):
    status: Optional[ActionStatus] = None
    error_message: Optional[str] = None
    executed_at: Optional[datetime] = None
    rate_limit_reset: Optional[datetime] = None
    rate_limit_remaining: Optional[int] = None
    metadata: Optional[ActionMetadata] = None

class ActionRead(ActionBase):
    id: int
    task_id: Optional[int]
    tweet_id: Optional[str]
    status: ActionStatus
    error_message: Optional[str]
    created_at: datetime
    executed_at: Optional[datetime]
    rate_limit_reset: Optional[datetime]
    rate_limit_remaining: Optional[int]

    class Config:
        from_attributes = True

class ActionImport(BaseModel):
    """Schema for importing actions from CSV"""
    account_no: str = Field(..., description="Account identifier")
    task_type: str = Field(..., description="Action type (like, RT, reply, quote, post)")
    source_tweet: str = Field(..., description="URL of tweet to act on (not required for post)")
    text_content: Optional[str] = Field(None, description="Required for reply, quote, and post actions")
    media: Optional[str] = Field(None, description="Optional media file path")
    priority: Optional[int] = Field(0, description="Action priority (higher = more priority)")
    api_method: Optional[str] = Field('graphql', description="API method to use (graphql or rest)")

    @validator('api_method')
    def validate_api_method(cls, v):
        if v and v.lower() not in ['graphql', 'rest']:
            raise ValueError("API method must be either 'graphql' or 'rest'")
        return v.lower()

    @validator('task_type')
    def validate_task_type(cls, v):
        # Map CSV task types to internal action types
        task_type_map = {
            'like': 'like_tweet',
            'rt': 'retweet_tweet',
            'retweet': 'retweet_tweet',
            'reply': 'reply_tweet',
            'quote': 'quote_tweet',
            'post': 'create_tweet'
        }
        
        normalized = v.lower()
        if normalized not in task_type_map:
            raise ValueError(f"Invalid task type. Must be one of: {', '.join(task_type_map.keys())}")
        
        return task_type_map[normalized]

    @validator('source_tweet')
    def validate_source_tweet(cls, v, values):
        task_type = values.get('task_type')
        
        # create_tweet doesn't require a source tweet
        if task_type == 'create_tweet':
            return None
        
        # other actions require a valid tweet URL
        if not v or not ('twitter.com' in v or 'x.com' in v):
            raise ValueError("Invalid tweet URL format")
        
        return v

    @validator('text_content')
    def validate_text_content(cls, v, values):
        task_type = values.get('task_type')
        
        # Validate required text_content for certain action types
        if task_type in ['reply_tweet', 'quote_tweet', 'create_tweet'] and not v:
            raise ValueError(f"{task_type} requires text content")
        
        return v

class ActionBulkCreate(BaseModel):
    """Schema for bulk action creation"""
    actions: list[ActionCreate]

class TweetData(BaseModel):
    """Schema for tweet data"""
    id: str
    text: str
    author: str
    created_at: str
    media: Optional[list[Dict[str, Any]]]
    metrics: Optional[Dict[str, int]]
    urls: Optional[list[Dict[str, str]]]
    tweet_url: str

class ActionStatus(BaseModel):
    """Schema for action status response"""
    id: int
    status: ActionStatus
    type: ActionType
    tweet_id: Optional[str]
    created_at: datetime
    executed_at: Optional[datetime]
    error: Optional[str]
    metadata: Optional[ActionMetadata]
    rate_limit_info: Optional[Dict[str, Any]]
    
    # Source tweet data
    source_tweet: Optional[TweetData]
    
    # For replies/quotes: the content being posted
    content: Optional[str]
    media: Optional[list[Dict[str, Any]]]
    
    # For completed actions: the resulting tweet
    result_tweet: Optional[TweetData]
