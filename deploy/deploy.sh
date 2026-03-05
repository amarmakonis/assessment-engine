#!/usr/bin/env bash
# Run this on EC2 after cloning project and configuring .env
# To skip frontend build (e.g. you built locally or only changed backend): SKIP_FRONTEND_BUILD=1 ./deploy/deploy.sh
set -e
cd "$(dirname "$0")/.."

if [[ -z "${SKIP_FRONTEND_BUILD}" ]]; then
  echo "Building frontend..."
  cd frontend
  npm ci
  npm run build
  cd ..
else
  echo "Skipping frontend build (SKIP_FRONTEND_BUILD is set). Ensure frontend/dist exists."
fi

echo "Starting services..."
docker compose -f docker-compose.production.yml up -d --build

echo "Deployment complete. Check status:"
docker compose -f docker-compose.production.yml ps
