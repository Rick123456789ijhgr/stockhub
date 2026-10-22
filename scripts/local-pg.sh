#!/usr/bin/env bash
# Docker-free local Postgres: a private cluster under .local/pgdata on port 5433,
# mirroring docker-compose.yml (user/password stockhub, databases stockhub + stockhub_test).
# Usage: scripts/local-pg.sh init|start|stop|status
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$ROOT/.local/pgdata"
LOG="$ROOT/.local/pg.log"
PORT="${POSTGRES_PORT:-5433}"
if [[ -n "${PG_BIN:-}" ]]; then
  BIN="$PG_BIN/"
elif command -v pg_ctl >/dev/null 2>&1; then
  BIN=""
else
  BIN="$(ls -d /c/Program\ Files/PostgreSQL/*/bin 2>/dev/null | sort -V | tail -1)/"
fi

pgctl() { "${BIN}pg_ctl" -D "$DATA" "$@"; }

# Memory for a single-user machine (docs/DECISIONS.md D-117): the default 128 MB of shared
# buffers holds a fraction of prices_daily, so first opens of a stock read from disk.
# Same settings as docker-compose.yml.
TUNING="-c shared_buffers=2GB -c effective_cache_size=12GB -c work_mem=32MB -c random_page_cost=1.1"

case "${1:-}" in
  init)
    mkdir -p "$ROOT/.local"
    pwfile="$(mktemp)"; echo stockhub >"$pwfile"
    "${BIN}initdb" -D "$DATA" -U stockhub --pwfile="$pwfile" --auth=scram-sha-256 -E UTF8 --locale=C >/dev/null
    rm -f "$pwfile"
    "$0" start
    PGPASSWORD=stockhub "${BIN}psql" -h localhost -p "$PORT" -U stockhub -d postgres -q \
      -c "CREATE DATABASE stockhub" -c "CREATE DATABASE stockhub_test"
    echo "initialized cluster at $DATA (port $PORT)"
    ;;
  start)
    # Redirect every stream: on Windows pg_ctl otherwise keeps the caller's pipes open.
    pgctl -o "-p $PORT -c listen_addresses=localhost -c timezone=UTC $TUNING" -l "$LOG" -w start </dev/null >/dev/null 2>&1
    echo "postgres listening on localhost:$PORT"
    ;;
  stop) pgctl -m fast stop ;;
  status) pgctl status ;;
  *) echo "usage: $0 init|start|stop|status" >&2; exit 2 ;;
esac
