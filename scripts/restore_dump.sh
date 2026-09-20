#!/bin/bash
# Drop the current Lads Beer database and restore a PostgreSQL custom dump.
#
# Usage:
#   ./scripts/restore_dump.sh [dump-file] [--yes]
#
# Destructive: drops and recreates the target database before restoring.
# The app container is stopped during the restore and started again afterwards,
# so startup migrations/seed run against the restored data.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

DEFAULT_DUMP="backup_ladsbeer_completo_20260915_175358.dump"
DUMP="$DEFAULT_DUMP"
ASSUME_YES=0

for arg in "$@"; do
    case "$arg" in
        --yes|-y) ASSUME_YES=1 ;;
        *) DUMP="$arg" ;;
    esac
done

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

DB_CONTAINER="${DB_CONTAINER:-ladsbeer-db}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-ladsbeer}"
APP_CONTAINER="${APP_CONTAINER:-ladsbeer-app}"
COMPOSE="${COMPOSE:-docker compose}"

if [ ! -f "$DUMP" ]; then
    echo "[ERROR] Dump not found: $DUMP" >&2
    exit 1
fi

if ! docker inspect "$DB_CONTAINER" >/dev/null 2>&1; then
    echo "[ERROR] Database container not found: $DB_CONTAINER" >&2
    exit 1
fi

echo "[1/6] Validating dump: $DUMP"
if ! docker exec -i "$DB_CONTAINER" pg_restore --list < "$DUMP" >/dev/null 2>&1; then
    echo "[ERROR] Not a valid PostgreSQL custom dump" >&2
    exit 1
fi

if [ "$ASSUME_YES" -ne 1 ]; then
    read -r -p "This will DROP database '$DB_NAME' and restore '$DUMP'. Continue? [y/N] " answer
    case "$answer" in
        [yY]) ;;
        *) echo "Cancelled."; exit 0 ;;
    esac
fi

echo "[2/6] Stopping the app..."
$COMPOSE stop app >/dev/null

echo "[3/6] Dropping and recreating database '$DB_NAME'..."
docker exec "$DB_CONTAINER" dropdb -U "$DB_USER" --if-exists --force "$DB_NAME"
docker exec "$DB_CONTAINER" createdb -U "$DB_USER" -O "$DB_USER" "$DB_NAME"

echo "[4/6] Restoring dump (single transaction)..."
docker exec -i "$DB_CONTAINER" pg_restore \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --no-owner \
    --no-acl \
    --single-transaction < "$DUMP"

echo "[5/6] Starting the app (migrations/seed run on startup)..."
$COMPOSE up -d app >/dev/null

echo "[6/6] Waiting for the app healthcheck..."
for _ in $(seq 1 60); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$APP_CONTAINER" 2>/dev/null || echo unknown)"
    if [ "$status" = "healthy" ]; then
        break
    fi
    sleep 2
done

applied="$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT COUNT(*) FROM schema_migrations;")"
echo "Migrations applied: $applied"
$COMPOSE ps app
echo "Restore finished. Follow the logs with: $COMPOSE logs -f app"
