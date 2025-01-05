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
