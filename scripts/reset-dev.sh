#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/backups
if [ -f data/quick_capture.db ]; then
  cp data/quick_capture.db "data/backups/quick_capture.$(date +%Y%m%d-%H%M%S).db"
fi
rm -f data/quick_capture.db
docker compose up -d --build quick-capture
echo "reset done"
echo "db: data/quick_capture.db"
echo "admin password source: docker-compose.yml -> QUICK_CAPTURE_ADMIN_PASSWORD"
