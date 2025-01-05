#!/bin/bash

# Exit on error
set -e

echo "Setting up development environment..."

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -e .
pip install -r requirements.txt

# Create necessary directories
echo "Creating necessary directories..."
mkdir -p logs
mkdir -p backend/logs

# Run database migrations
echo "Running database migrations..."
alembic upgrade head

# Install frontend dependencies
echo "Installing frontend dependencies..."
cd frontend
npm install
cd ..

# Make run_worker.py executable
chmod +x run_worker.py

echo "
Development environment setup complete!

To start the development servers:

1. Start the backend API:
   uvicorn backend.app.main:app --reload --port 9000

2. Start the task worker:
   ./run_worker.py

3. Start the frontend:
   cd frontend && npm run dev

The API will be available at: http://localhost:9000
The frontend will be available at: http://localhost:3000
"

# Create a helper script to start all services
cat > start-dev.sh << 'EOF'
#!/bin/bash

# Start backend API
echo "Starting backend API..."
uvicorn backend.app.main:app --reload --port 9000 &
BACKEND_PID=$!

# Start task worker
echo "Starting task worker..."
./run_worker.py &
WORKER_PID=$!

# Start frontend
echo "Starting frontend..."
cd frontend && npm run dev &
FRONTEND_PID=$!

# Function to kill all processes
cleanup() {
    echo "Shutting down services..."
    kill $BACKEND_PID 2>/dev/null
    kill $WORKER_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit 0
}

# Set up trap for cleanup
trap cleanup SIGINT SIGTERM

# Wait for any process to exit
wait -n

# If any process exits, kill the others
cleanup
EOF

chmod +x start-dev.sh

echo "
A helper script 'start-dev.sh' has been created to start all services at once.
To use it, run: ./start-dev.sh
"
