#!/bin/sh
# Restore a backup made by backup.sh into the running db container.
# Usage: ./scripts/restore.sh backups/aignews-20261024-0330.dump.gz
set -eu
FILE="${1:?usage: restore.sh <file.dump.gz>}"
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
echo "Restoring $FILE into ${POSTGRES_DB:-aignews} (existing objects will be dropped)..."
gunzip -c "$FILE" | docker compose exec -T db pg_restore -U "${POSTGRES_USER:-aignews}" -d "${POSTGRES_DB:-aignews}" --clean --if-exists --no-owner --no-privileges
echo "done"
