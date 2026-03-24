#!/usr/bin/env bash
# Start Redis (if docker-compose is available), Flask API, Celery worker, and Vite frontend.
# Usage: ./run-dev.sh   (from project root, or: bash run-dev.sh)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

PY="$BACKEND/.venv/bin/python"
CELERY="$BACKEND/.venv/bin/celery"

if [[ ! -x "$PY" ]]; then
  echo "Missing backend venv. Run: cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

if [[ ! -d "$FRONTEND/node_modules" ]]; then
  echo "Installing frontend dependencies..."
  (cd "$FRONTEND" && npm install)
fi

if command -v docker-compose >/dev/null 2>&1; then
  (cd "$ROOT" && docker-compose up -d) 2>/dev/null || true
fi

cleanup() {
  if [[ -n "${PID_FLASK:-}" ]]; then kill "$PID_FLASK" 2>/dev/null || true; fi
  if [[ -n "${PID_CELERY:-}" ]]; then kill "$PID_CELERY" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM

cd "$BACKEND"
"$PY" app.py &
PID_FLASK=$!

"$CELERY" -A celery_app worker --loglevel=info &
PID_CELERY=$!

echo "API:    http://127.0.0.1:5001"
echo "Worker: Celery (PID $PID_CELERY)"
echo "UI:     http://localhost:3000  (Ctrl+C stops API, worker, and dev server)"
echo ""

cd "$FRONTEND"
npm run dev
