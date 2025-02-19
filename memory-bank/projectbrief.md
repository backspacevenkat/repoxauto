# Xauto Project Brief

## Project Overview
Xauto is a comprehensive Twitter account management and automation platform designed to handle both account validation/recovery and data scraping operations through a task-based system. The platform supports multi-account management with sophisticated proxy handling, rate limiting, and automated workflows.

## Core Requirements

### Account Management
- Import and manage multiple Twitter accounts
- Support for both "Normal" and "Worker" account types
- Automated account validation and recovery
- Secure credential management
- Proxy support with automatic URL encoding
- Captcha solving integration (2captcha)
- Email verification handling

### Task System
- Profile and tweet scraping capabilities
- Rate limiting and queue management
- Batch processing support
- Real-time monitoring
- Task analytics and reporting

### Technical Requirements
- Scalable architecture supporting multiple concurrent operations
- Real-time updates via WebSocket
- Secure credential storage
- Database migrations support
- Multi-threaded processing
- Comprehensive logging
- Error handling and recovery

## Technology Stack

### Backend
- Python 3.11+
- FastAPI for REST API
- SQLAlchemy for ORM
- PostgreSQL for database
- Redis for task queue
- Playwright for browser automation
- Celery for task processing

### Frontend
- Next.js
- React
- Tailwind CSS/Material UI
- WebSocket for real-time updates

### Infrastructure
- Docker for containerization
- Redis for queue management
- 2captcha for CAPTCHA solving
- Proxy management system

## Security Requirements
- Secure storage of account credentials
- Encrypted proxy configurations
- Safe handling of API keys
- Role-based access control
- Secure session management

## Integration Points
- Twitter API
- 2captcha API
- Email verification systems
- Proxy providers
- Monitoring systems

## Success Criteria
1. Reliable account validation and recovery
2. Efficient task processing with rate limit compliance
3. Scalable multi-account management
4. Real-time monitoring and alerts
5. Comprehensive error handling and recovery
6. User-friendly interface for account and task management

## Project Scope
- Account management and validation
- Task creation and monitoring
- Data scraping and collection
- Analytics and reporting
- System monitoring and maintenance
- User interface for management
- API for external integration

## Out of Scope
- Social media posting/engagement
- Content creation
- Analytics beyond basic metrics
- External API provision
- Custom proxy implementation

This brief serves as the foundation for all development work and technical decisions in the Xauto project. All features and implementations should align with these core requirements and objectives.
