#!/usr/bin/env bash
# Run this on EC2 after cloning project and configuring .env
set -e
cd "$(dirname "$0")/.."

echo "Building frontend..."
cd frontend
npm ci
npm run build
cd ..

echo "Starting services..."
docker compose -f docker-compose.production.yml up -d --build

echo "Deployment complete. Check status:"
docker compose -f docker-compose.production.yml ps
