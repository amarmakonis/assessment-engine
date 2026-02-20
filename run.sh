#!/usr/bin/env bash
# Run entire Assessment Engine with one command.
# Starts MongoDB, Redis (Docker), Flask, Celery, and Frontend. Ctrl+C stops everything.

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

FLASK_PID=""
CELERY_PID=""
DOCKER_MONGO=false
DOCKER_REDIS=false

cleanup() {
  echo ""
  echo "Shutting down..."
  [ -n "$FLASK_PID" ] && kill "$FLASK_PID" 2>/dev/null || true
  [ -n "$CELERY_PID" ] && kill "$CELERY_PID" 2>/dev/null || true
  if [ "$DOCKER_MONGO" = true ]; then
    docker stop mongo 2>/dev/null || true
  fi
  if [ "$DOCKER_REDIS" = true ]; then
    docker stop redis 2>/dev/null || true
  fi
  exit 0
}
trap cleanup SIGINT SIGTERM

# Check if port is in use (MongoDB/Redis may already be running)
port_in_use() {
  if command -v nc &>/dev/null; then
    nc -z localhost "$1" 2>/dev/null
  else
    timeout 1 bash -c "echo >/dev/tcp/localhost/$1" 2>/dev/null
  fi
}

# Start MongoDB via Docker (only if port 27017 is free)
if port_in_use 27017; then
  echo "MongoDB already available on port 27017"
elif docker ps -q -f name=^mongo$ 2>/dev/null | grep -q .; then
  echo "MongoDB already running"
elif docker ps -aq -f name=^mongo$ 2>/dev/null | grep -q .; then
  echo "Starting MongoDB container..."
  docker start mongo
  DOCKER_MONGO=true
else
  echo "Starting MongoDB container..."
  docker run -d -p 27017:27017 --name mongo mongo:7
  DOCKER_MONGO=true
fi

# Start Redis via Docker (only if port 6379 is free)
if port_in_use 6379; then
  echo "Redis already available on port 6379"
elif docker ps -q -f name=^redis$ 2>/dev/null | grep -q .; then
  echo "Redis already running"
elif docker ps -aq -f name=^redis$ 2>/dev/null | grep -q .; then
  echo "Starting Redis container..."
  docker start redis
  DOCKER_REDIS=true
else
  echo "Starting Redis container..."
  docker run -d -p 6379:6379 --name redis redis:7-alpine
  DOCKER_REDIS=true
fi

# Wait for MongoDB and Redis to accept connections
echo "Waiting for MongoDB and Redis..."
sleep 3

echo "Starting Flask backend..."
cd "$BACKEND"
source venv/bin/activate 2>/dev/null || . venv/Scripts/activate 2>/dev/null || true
python -m flask run --host=0.0.0.0 --port=5000 &
FLASK_PID=$!

echo "Starting Celery worker..."
celery -A celery_app:celery worker -Q ocr,evaluation,default -l info &
CELERY_PID=$!

sleep 2

echo "Starting frontend..."
cd "$FRONTEND"
npm run dev
