# Xauto Technical Context

## Development Environment

### Core Requirements
- Python 3.11+
- Node.js 16+
- PostgreSQL
- Redis
- 2captcha API key
- Docker (optional)

### Python Dependencies
Key packages and their purposes:

#### Web Framework & API
- fastapi==0.104.1: Main web framework
- uvicorn==0.24.0: ASGI server
- websockets==12.0: WebSocket support
- python-multipart==0.0.6: Form data handling

#### Database
- sqlalchemy==2.0.23: ORM
- asyncpg==0.29.0: Async PostgreSQL driver
- alembic==1.12.1: Database migrations
- aiosqlite==0.19.0: Async SQLite support

#### Task Processing
- celery==5.3.6: Task queue
- redis==5.0.1: Queue backend
- aioredis==2.0.1: Async Redis client
- kombu==5.4.2: Messaging library

#### Database
- Added worker_account_id column to Task model

#### Browser Automation
- playwright==1.39.0: Browser automation
- pyee==11.0.1: Event emitter
- 2captcha-python==1.2.0: CAPTCHA solving

#### HTTP & Networking
- aiohttp==3.9.1: Async HTTP client
- httpx==0.26.0: Modern HTTP client
- requests==2.31.0: HTTP client
- python-socks==2.4.3: SOCKS proxy support

#### Security
- python-jose==3.3.0: JWT handling
- passlib==1.7.4: Password hashing
- bcrypt==4.0.1: Password hashing
- cryptography==44.0.0: Cryptographic operations

#### Data Processing
- pandas==2.1.3: Data manipulation
- numpy==1.26.4: Numerical operations
- beautifulsoup4==4.12.2: HTML parsing
- lxml==5.3.0: XML/HTML processing

#### Development Tools
- black==23.11.0: Code formatting
- flake8==6.1.0: Linting
- mypy==1.7.1: Type checking
- isort==5.12.0: Import sorting

#### Testing
- pytest==7.4.3: Testing framework
- pytest-asyncio==0.21.1: Async test support
- pytest-cov==4.1.0: Coverage reporting
- pytest-mock==3.12.0: Mocking support

### Frontend Dependencies
From package.json:
```json
{
  "dependencies": {
    "@emotion/react": "^11.11.1",
    "@emotion/styled": "^11.11.0",
    "@mui/icons-material": "^5.15.1",
    "@mui/material": "^5.15.1",
    "axios": "^1.6.2",
    "date-fns": "^4.1.0",
    "next": "^14.0.4",
    "notistack": "^3.0.2",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-dropzone": "^14.3.5"
  }
}
```

Key Frontend Features:
1. **Material UI Components**
   - Consistent styling
   - Responsive design
   - Theme customization

2. **Real-time Updates**
   - WebSocket integration
   - Connection management
   - Status broadcasting

3. **File Handling**
   - Drag-and-drop support
   - CSV import/export
   - File validation

4. **Notifications**
   - Toast notifications
   - Error handling
   - Status updates

## Development Setup

### Environment Variables
```bash
# Database Configuration
DATABASE_URL="postgresql+asyncpg://user:password@localhost/xauto"
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=10

# Redis Configuration
REDIS_URL="redis://localhost:6379/0"
REDIS_MAX_CONNECTIONS=50

# API Keys & Services
TWO_CAPTCHA_API_KEY="your-api-key"
TWO_CAPTCHA_TIMEOUT=60

# WebSocket Configuration
WS_HOST="localhost"
WS_PORT=9000
WS_HEARTBEAT_INTERVAL=15

# Task Processing
MAX_WORKERS=6
BATCH_SIZE=10
RATE_LIMIT_WINDOW=900
MAX_RETRIES=3

# Proxy Configuration
PROXY_ROTATION_INTERVAL=300
MAX_PROXY_RETRIES=5

# Frontend Configuration
NEXT_PUBLIC_API_URL="http://localhost:9000"
NEXT_PUBLIC_WS_URL="ws://localhost:9000/ws"

# Logging & Debug
DEBUG=True
LOG_LEVEL=INFO
LOG_FORMAT="%(asctime)s [%(levelname)s] %(message)s"
LOG_FILE="app.log"
```

### Database Setup
1. Create PostgreSQL database:
```sql
CREATE DATABASE xauto;
CREATE USER xauto_user WITH PASSWORD 'password';
GRANT ALL PRIVILEGES ON DATABASE xauto TO xauto_user;
```

2. Configure connection pool:
```python
engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800
)
```

3. Run migrations:
```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback if needed
alembic downgrade -1
```

4. Verify setup:
```bash
# Check connection
python -c "from backend.database import db_manager; print(db_manager.is_connected)"

# Test migrations
alembic check
```

### Development Scripts
```bash
# Initial Setup
./dev-setup.sh
```
```python
# dev-setup.sh contents
#!/bin/bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
playwright install

# Setup database
alembic upgrade head

# Install frontend dependencies
cd frontend && npm install
```

```bash
# Start Development Services
./start-dev.sh
```
```python
# start-dev.sh contents
#!/bin/bash
# Start Redis
redis-server &

# Start backend
uvicorn backend.app.main:app --reload --port 9000 &

# Start frontend
cd frontend && npm run dev &

# Start task workers
celery -A backend.app.worker worker --loglevel=info &

# Wait for all processes
wait
```

## Project Structure

### Backend Structure
```
backend/
├── app/
│   ├── models/          # SQLAlchemy models
│   ├── routers/         # API endpoints
│   ├── schemas/         # Pydantic schemas
│   ├── services/        # Business logic
│   └── tests/          # Test files
├── migrations/         # Alembic migrations
└── alembic.ini        # Migration config
```

### Frontend Structure
```
frontend/
├── components/         # React components
├── pages/             # Next.js pages
├── public/            # Static files
├── styles/            # CSS styles
└── services/          # API clients
```

## Development Workflows

### Code Style
- Black for Python formatting
- Flake8 for Python linting
- ESLint for JavaScript
- Prettier for frontend formatting

### Testing
```bash
# Backend Tests
pytest backend/app/tests/

# Frontend Tests
cd frontend && npm test
```

### Database Migrations
```bash
# Create migration
alembic revision -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Deployment

### Docker Setup
```dockerfile
# Example Dockerfile structure
FROM python:3.11
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "backend.app.main:app"]
```

### Production Considerations
1. **Environment**
   - Use production-grade servers
   - Configure proper logging
   - Set up monitoring
   - Enable SSL/TLS

2. **Security**
   - Secure all endpoints
   - Encrypt sensitive data
   - Use proper authentication
   - Implement rate limiting

3. **Performance**
   - Configure proper worker counts
   - Set up caching
   - Optimize database queries
   - Monitor resource usage

## Monitoring & Logging

### Logging Configuration
```python
# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
```

### Health Checks
- Database connectivity
- Redis availability
- External service status
- Worker health

### Metrics
- Request latency
- Error rates
- Task queue length
- Resource utilization

## External Services

### Twitter Integration
- Rate limits: 900 requests/15min
- Authentication requirements
- API endpoints used
- Error handling

### 2captcha Integration
- API key configuration
- Balance management
- Response handling
- Error recovery

#### FunCaptcha Configuration
```python
# Task Types
FunCaptchaTask:  # When using own proxies
    type: "FunCaptchaTask"  # Important: Use this when providing proxy details
    websiteURL: str  # Full URL where captcha is loaded
    websitePublicKey: str  # ArkoseLabs public key
    funcaptchaApiJSSubdomain: str  # Optional, custom subdomain
    proxyType: str  # 'http', 'socks4', or 'socks5'
    proxyAddress: str  # Proxy IP or hostname
    proxyPort: int  # Proxy port
    proxyLogin: str  # Optional proxy authentication
    proxyPassword: str  # Optional proxy authentication
    userAgent: str  # Browser User-Agent

FunCaptchaTaskProxyless:  # When using 2captcha's proxies
    type: "FunCaptchaTaskProxyless"
    websiteURL: str
    websitePublicKey: str
    funcaptchaApiJSSubdomain: str  # Optional
    userAgent: str

# Implementation Notes
- Use FunCaptchaTask (not Proxyless) when providing proxy details
- Ensure all proxy parameters are included when using FunCaptchaTask
- Verify proxy authentication if required
- Use consistent User-Agent across requests

# Example Implementation
```python
class CaptchaSolver:
    async def solve_funcaptcha(self, page, proxy_config):
        task_config = {
            "type": "FunCaptchaTask",  # Not Proxyless when using proxies
            "websiteURL": page.url,
            "websitePublicKey": self.get_public_key(page),
            "funcaptchaApiJSSubdomain": "client-api.arkoselabs.com",
            "userAgent": await page.evaluate("navigator.userAgent"),
            # Proxy configuration
            "proxyType": "http",
            "proxyAddress": proxy_config['proxy_url'],
            "proxyPort": proxy_config['proxy_port'],
            "proxyLogin": proxy_config['proxy_username'],
            "proxyPassword": proxy_config['proxy_password']
        }
        return await self.submit_captcha_task(task_config)
```
```

### Proxy Management
- Proxy rotation
- Authentication
- Health checking
- Error handling

This technical context document serves as a comprehensive reference for the development environment, dependencies, and technical considerations of the Xauto project.
