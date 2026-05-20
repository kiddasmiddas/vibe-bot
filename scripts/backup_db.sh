#!/usr/bin/env bash
# backup_db.sh — ежесуточный pg_dump текущей БД в tar.gz с ротацией 7 копий.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
DB_HOST="${POSTGRES_HOST:-postgres}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_NAME="${POSTGRES_DB:-vibe}"
DB_USER="${POSTGRES_USER:-vibe}"

DATE=$(date -u +%Y-%m-%d_%H-%M-%S)

mkdir -p "$BACKUP_DIR"

PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    "$DB_NAME" \
    | gzip > "$BACKUP_DIR/vibe-$DATE.sql.gz"

# Ротация: оставляем 7 последних архивов.
ls -1t "$BACKUP_DIR"/vibe-*.sql.gz | tail -n +8 | xargs -r rm -f

echo "Backup created: vibe-$DATE.sql.gz"
