#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGDATA_DIR="${PGDATA_DIR:-$ROOT_DIR/pgdata}"
LOG_FILE="${LOG_FILE:-$ROOT_DIR/logs/postgres.log}"
PORT="${PGPORT:-5432}"

mkdir -p "$PGDATA_DIR" "$(dirname "$LOG_FILE")"
chmod 700 "$PGDATA_DIR"
chown -R postgres:postgres "$PGDATA_DIR" "$(dirname "$LOG_FILE")"

if [ ! -f "$PGDATA_DIR/PG_VERSION" ]; then
  echo "Initializing PostgreSQL data directory at $PGDATA_DIR..."
  sudo -u postgres initdb -D "$PGDATA_DIR" --encoding=UTF8 --locale=C.UTF-8
fi

echo "Starting PostgreSQL on port $PORT..."
sudo -u postgres pg_ctl -D "$PGDATA_DIR" -l "$LOG_FILE" -o "-p $PORT" start
