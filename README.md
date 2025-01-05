# Xauto - Twitter Account Management System

A comprehensive Twitter account management and automation platform that supports both account validation/recovery and data scraping operations through a task-based system.

## Features

### Account Management
- Import accounts from CSV files
- Validate account status
- Automatic account recovery
- Bulk validation support
- Proxy support with automatic URL encoding
- Captcha solving integration
- Email verification handling

### Task System
- Profile scraping
- Tweet scraping (configurable count)
- Rate limiting and queue management
- Batch processing via CSV uploads
- Real-time task monitoring
- Detailed task results and analytics

### General Features
- Modern web interface
- RESTful API
- Database migrations
- Multi-threaded processing
- Detailed logging
- Real-time status updates

## Prerequisites

- Python 3.11+
- Node.js 16+
- PostgreSQL
- Playwright
- 2captcha API key (for captcha solving)
- Redis (for task queue)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/xauto.git
cd xauto
```

2. Run the development setup script:
```bash
chmod +x dev-setup.sh
./dev-setup.sh
```

This will:
- Create a Python virtual environment
- Install Python dependencies
- Install Playwright
- Install frontend dependencies
- Set up the database
- Create necessary directories
- Create helper scripts

## Configuration

1. Set up environment variables:
```bash
export DATABASE_URL="postgresql+asyncpg://user:password@localhost/xauto"
export TWO_CAPTCHA_API_KEY="your-api-key"
export REDIS_URL="redis://localhost:6379/0"
```

## Running the Application

Use the provided start script to run all services:
```bash
./start-dev.sh
```

Or start services individually:

1. Start the backend API:
```bash
uvicorn backend.app.main:app --reload --port 9000
```

2. Start the task worker:
```bash
./run_worker.py
```

3. Start the frontend development server:
```bash
cd frontend && npm run dev
```

## Usage

### Account Management

1. **Importing Accounts**
   - Prepare a CSV file with required columns:
     - account_no
     - login
     - auth_token
     - ct0
     - proxy_url
     - proxy_port
     - proxy_username
     - proxy_password
   - Use the web interface to import

2. **Validating Accounts**
   - Individual validation via UI
   - Bulk validation with configurable threads
   - Automatic recovery attempts for failed accounts

### Task System

1. **Profile Scraping**
   - Upload CSV with usernames
   - Select task type "Scrape Profile"
   - Monitor progress in real-time
   - View detailed results

2. **Tweet Scraping**
   - Upload CSV with usernames
   - Select task type "Scrape Tweets"
   - Configure tweet count (1-100)
   - Monitor progress and view results

3. **Batch Processing**
   - Upload CSV files
   - Configure task parameters
   - Monitor task queue
   - Download results

## Project Structure

```
xauto/
├── backend/
│   ├── app/
│   │   ├── models/          # Database models
│   │   ├── routers/         # API endpoints
│   │   ├── schemas/         # Pydantic schemas
│   │   ├── services/        # Business logic
│   │   └── tests/          # Test files
│   └── migrations/         # Database migrations
├── frontend/
│   ├── components/         # React components
│   ├── pages/             # Next.js pages
│   └── public/            # Static files
├── logs/                  # Application logs
└── screenshots/          # Account validation screenshots
```

## Development

### Database Migrations

Create a new migration:
```bash
alembic revision -m "description"
```

Apply migrations:
```bash
alembic upgrade head
```

### Running Tests
```bash
pytest backend/app/tests/
```

### Code Style
```bash
black .
isort .
flake8
mypy .
```

## API Documentation

Access the API documentation at:
- Swagger UI: `http://localhost:9000/docs`
- ReDoc: `http://localhost:9000/redoc`

## Rate Limiting

The system implements Twitter's rate limits:
- Profile requests: 900/15min window
- Tweet requests: 900/15min window
- Per-account tracking
- Automatic backoff and retry

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
