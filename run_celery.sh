#!/usr/bin/env bash
# Run Celery workers for Assessment Engine (requires Redis, USE_CELERY_REDIS=true).
# Each worker evaluates different questions in parallel → higher throughput.
# Ensure Redis and MongoDB are running before starting.
#
# Usage:
#   ./run_celery.sh              # Start both OCR and evaluation workers
#   ./run_celery.sh ocr          # OCR worker only
#   ./run_celery.sh evaluation   # Evaluation worker only
#
# Concurrency: set CELERY_WORKER_CONCURRENCY in .env (default: 4)

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"

cd "$BACKEND"
source venv/bin/activate 2>/dev/null || . venv/Scripts/activate 2>/dev/null || true

# Load .env if present
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi
if [ -f "$ROOT/.env" ]; then
  set -a
  source "$ROOT/.env"
  set +a
fi

CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-4}"
QUEUE="${1:-all}"

echo "Celery workers — concurrency=$CONCURRENCY, queue=$QUEUE"
echo "Ensure Redis is running (localhost:6379) and USE_CELERY_REDIS=true"
echo ""

case "$QUEUE" in
  ocr)
    celery -A celery_app.celery worker \
      -Q ocr,default \
      -l info \
      --concurrency="$CONCURRENCY"
    ;;
  evaluation)
    celery -A celery_app.celery worker \
      -Q evaluation \
      -l info \
      --concurrency="$CONCURRENCY"
    ;;
  all)
    echo "Starting OCR worker (background)..."
    celery -A celery_app.celery worker \
      -Q ocr,default \
      -l info \
      --concurrency="$CONCURRENCY" &
    OCR_PID=$!
    sleep 2
    echo "Starting Evaluation worker (foreground)..."
    celery -A celery_app.celery worker \
      -Q evaluation \
      -l info \
      --concurrency="$CONCURRENCY"
    wait $OCR_PID 2>/dev/null || true
    ;;
  *)
    echo "Usage: $0 [ocr|evaluation|all]"
    echo "  ocr        — OCR worker only"
    echo "  evaluation — Evaluation worker only"
    echo "  all        — Both workers (OCR in background, evaluation foreground)"
    exit 1
    ;;
esac
