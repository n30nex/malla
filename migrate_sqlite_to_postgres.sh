#!/bin/sh
set -e

SQLITE_DB_PATH="${SQLITE_DB_PATH:-/app/sqlite_data/meshtastic_history.db}"
PGLOADER_CONN="${PGLOADER_CONN:-postgresql://malla:malla_pw@postgres:5432/meshtastic_db}"

if [ ! -f "$SQLITE_DB_PATH" ]; then
  echo "No SQLite database found at $SQLITE_DB_PATH. Skipping migration."
  exit 0
fi

echo "Migrating $SQLITE_DB_PATH to $PGLOADER_CONN"
pgloader "$SQLITE_DB_PATH" "$PGLOADER_CONN"
echo "Migration finished."