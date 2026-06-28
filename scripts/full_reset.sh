#!/bin/bash
# Full reset for clean tests:
# 1. Stops uvicorn if running
# 2. Drops all tables and re-runs seed
# 3. Starts uvicorn again

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "Stopping uvicorn..."
pkill -f "uvicorn app.main:app" || true
sleep 1

echo "Resetting database..."
source .venv/bin/activate
python3 scripts/reset_db.py --force

echo "Starting uvicorn..."
setsid uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload > /tmp/uvicorn_ladsbeer.log 2>&1 < /dev/null &
sleep 3

echo "Done. Logs: /tmp/uvicorn_ladsbeer.log"
