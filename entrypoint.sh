#!/bin/bash
set -e

# Wait for PostgreSQL to be ready
python3 /app/scripts/wait_for_db.py

# Start the application with uvicorn
exec uvicorn app.main:app --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8000}"
