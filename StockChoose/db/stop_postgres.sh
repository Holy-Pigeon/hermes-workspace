#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGDATA_DIR="${PGDATA_DIR:-$ROOT_DIR/pgdata}"

echo "Stopping PostgreSQL..."
sudo -u postgres pg_ctl -D "$PGDATA_DIR" stop -m fast
