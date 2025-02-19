"""
Twitter API Client Package
A modern asynchronous Twitter API client with comprehensive functionality.
"""
from .http_client import TwitterHttpClient

# Version information
__version__ = '1.0.0'
__author__ = 'Your Name'
__author_email__ = 'your.email@example.com'
__description__ = 'Modern asynchronous Twitter API client'
__url__ = 'https://github.com/yourusername/twitter-client'
__license__ = 'MIT'

# Package level imports for easier access
__all__ = [
    'TwitterHttpClient',
    
    # Constants
    '__version__',
    '__author__',
    '__author_email__',
    '__description__',
    '__url__',
    '__license__'
]

# Package metadata
metadata = {
    'name': 'twitter-client',
    'version': __version__,
    'description': __description__,
    'author': __author__,
    'author_email': __author_email__,
    'url': __url__,
    'license': __license__,
    'classifiers': [
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Internet :: WWW/HTTP',
        'Operating System :: OS Independent',
    ],
    'keywords': [
        'twitter',
        'api',
        'client',
        'async',
        'social media',
    ],
    'requires': [
        'httpx>=0.24.0',
        'asyncio>=3.4.3',
    ],
}

# Optional: Set up logging configuration
import logging

# Create a logger for the package
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create console handler with formatting
handler = logging.StreamHandler()
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
handler.setFormatter(formatter)
logger.addHandler(handler)

# Version compatibility check
import sys
if sys.version_info < (3, 7):
    raise RuntimeError("This package requires Python 3.7+")

# Clean up namespace
del sys