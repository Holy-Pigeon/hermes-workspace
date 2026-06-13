#!/usr/bin/env bash
set -euo pipefail

DB_NAME="${DB_NAME:-stockchoose}"
DB_USER="${DB_USER:-postgres}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA_FILE="$SCRIPT_DIR/schema.sql"

if ! command -v psql >/dev/null 2>&1; then
  echo "ERROR: psql not found. Please install PostgreSQL client/server first." >&2
  exit 1
fi

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
  echo "Creating database ${DB_NAME}..."
  sudo -u postgres createdb "${DB_NAME}"
else
  echo "Database ${DB_NAME} already exists."
fi

echo "Applying schema ${SCHEMA_FILE}..."
sudo -u postgres psql -d "${DB_NAME}" -f "${SCHEMA_FILE}"

echo "Done. Database ${DB_NAME} is ready."
