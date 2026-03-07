#!/usr/bin/env bash
# Run Assessment Engine: Flask + Frontend + (optional) Celery workers.
# Sync (USE_CELERY_REDIS=false): OCR/eval in-process. Celery (true): needs Redis.
# Ensure MongoDB is running. UI: http://localhost:3000

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

FLASK_PID=""
CELERY_PIDS=""
FRONTEND_PID=""
[ -f "$ROOT/.env" ] && set -a && source "$ROOT/.env" && set +a
[ -f "$BACKEND/.env" ] && set -a && source "$BACKEND/.env" && set +a

cleanup() {
  echo ""
  echo "Shutting down (terminating all processes)..."
  [ -n "$FRONTEND_PID" ] && kill -9 "$FRONTEND_PID" 2>/dev/null || true
  [ -n "$FLASK_PID" ] && kill -9 "$FLASK_PID" 2>/dev/null || true
  for p in $CELERY_PIDS; do [ -n "$p" ] && kill -9 "$p" 2>/dev/null || true; done
  exit 0
}
trap cleanup SIGINT SIGTERM

# Check if MongoDB is reachable (optional; user may use Atlas)
port_in_use() {
  if command -v nc &>/dev/null; then
    nc -z localhost "$1" 2>/dev/null
  else
    timeout 1 bash -c "echo >/dev/tcp/localhost/$1" 2>/dev/null
  fi
}

if port_in_use 27017; then
  echo "MongoDB available on port 27017"
else
  echo "Note: MongoDB not detected on localhost:27017. Using MONGO_URI from .env (e.g. MongoDB Atlas)."
fi

cd "$BACKEND"
source venv/bin/activate 2>/dev/null || . venv/Scripts/activate 2>/dev/null || true

USE_CELERY="${USE_CELERY_REDIS:-false}"
if [ "$USE_CELERY" = "true" ] || [ "$USE_CELERY" = "1" ]; then
  if ! port_in_use 6379; then
    echo "Error: USE_CELERY_REDIS=true but Redis not running on 6379."
    echo "Start Redis: docker run -d -p 6379:6379 redis:alpine"
    exit 1
  fi
  echo "Starting Flask backend (Celery mode)..."
  python -m flask run --host=0.0.0.0 --port=5000 &
  FLASK_PID=$!
  sleep 2
  CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-4}"
  celery -A celery_app.celery worker -Q ocr,default -l info --concurrency="$CONCURRENCY" &
  CELERY_PIDS="$!"
  celery -A celery_app.celery worker -Q evaluation -l info --concurrency="$CONCURRENCY" &
  CELERY_PIDS="$CELERY_PIDS $!"
  sleep 3
else
  echo "Starting Flask backend (sync pipeline)..."
  python -m flask run --host=0.0.0.0 --port=5000 &
  FLASK_PID=$!
  sleep 2
fi

echo "Starting frontend (UI: http://localhost:3000)..."
cd "$FRONTEND"
npm run dev &
FRONTEND_PID=$!
wait
