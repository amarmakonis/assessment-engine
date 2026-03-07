#!/usr/bin/env bash
# Build frontend for production. No Docker — run backend and serve frontend manually.
# To skip frontend build: SKIP_FRONTEND_BUILD=1 ./deploy/deploy.sh
set -e
cd "$(dirname "$0")/.."

if [[ -z "${SKIP_FRONTEND_BUILD}" ]]; then
  echo "Building frontend..."
  cd frontend
  npm ci
  npm run build
  cd ..
  echo "Frontend built to frontend/dist"
else
  echo "Skipping frontend build (SKIP_FRONTEND_BUILD is set). Ensure frontend/dist exists."
fi

echo ""
echo "Deployment build complete. To run in production:"
echo "  1. Ensure MongoDB is running (or set MONGO_URI in .env for Atlas)"
echo "  2. Backend: cd backend && gunicorn -w 2 -b 0.0.0.0:5000 wsgi:app"
echo "  3. Frontend: serve frontend/dist (e.g. nginx, or: npx serve -s frontend/dist -l 3000)"
