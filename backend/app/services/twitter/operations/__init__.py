"""
Twitter API Operations Module
Contains all operation classes for different Twitter API functionalities
"""

from .tweets import TweetOperations
from .users import UserOperations
from .media import MediaOperations
from .direct_messages import DirectMessageOperations
from .trends import TrendOperations

__all__ = [
    'TweetOperations',
    'UserOperations',
    'MediaOperations',
    'DirectMessageOperations',
    'TrendOperations'
]

# Version of the operations module
__version__ = '1.0.0'