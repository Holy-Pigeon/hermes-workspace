#!/usr/bin/env bash
# macOS 专用：幂等启动本地 PostgreSQL（StockChoose 项目内 pgdata）
# 解决两个 macOS 坑：
#   1) Homebrew postgresql@17 是 keg-only，bin 不在 PATH
#   2) macOS 上 postmaster 启动报 "became multithreaded" —— 必须 LC_ALL=C
# 用法：bash ensure_postgres_macos.sh   (已在跑则直接返回 0)
set -euo pipefail

export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
export LC_ALL="C"
export LANG="C"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGDATA_DIR="${PGDATA_DIR:-$ROOT_DIR/pgdata}"
LOG_FILE="${LOG_FILE:-$ROOT_DIR/logs/postgres.log}"
PORT="${PGPORT:-5432}"

mkdir -p "$(dirname "$LOG_FILE")"

# 已在监听就直接返回
if pg_isready -h localhost -p "$PORT" >/dev/null 2>&1; then
  echo "PostgreSQL already running on port $PORT"
  exit 0
fi

# 数据目录不存在则初始化（超级用户 = postgres，匹配 dump owner）
if [ ! -f "$PGDATA_DIR/PG_VERSION" ]; then
  echo "Initializing data dir at $PGDATA_DIR (superuser=postgres)..."
  initdb -D "$PGDATA_DIR" --encoding=UTF8 --locale=C -U postgres
fi

echo "Starting PostgreSQL on port $PORT..."
pg_ctl -D "$PGDATA_DIR" -l "$LOG_FILE" -o "-p $PORT" -w start
pg_isready -h localhost -p "$PORT"
