#!/usr/bin/env bash
# Run a make target unattended (Windows Task Scheduler, cron): tool PATH, local Postgres,
# one log file per target and day under .local/logs (kept 30 days).
# Usage: scripts/scheduled.sh <make target> [make args...]   e.g. scripts/scheduled.sh etl-daily
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:?usage: $0 <make target> [make args...]}"
shift
LOGS="$ROOT/.local/logs"
mkdir -p "$LOGS"
LOG="$LOGS/$TARGET-$(date +%Y%m%d).log"
export PATH="$HOME/.local/bin:$PATH" UV_LINK_MODE=copy PYTHONIOENCODING=utf-8

{
  echo "=== $(date '+%F %T') make $TARGET $*"
  cd "$ROOT" || exit 1
  # Docker-free setup: the private cluster does not start with Windows.
  if [[ -d .local/pgdata ]] && ! scripts/local-pg.sh status >/dev/null 2>&1; then
    scripts/local-pg.sh start
  fi
  make "$TARGET" "$@"
  status=$?
  echo "=== $(date '+%F %T') exit $status"
  find "$LOGS" -name '*.log' -mtime +30 -delete 2>/dev/null
  exit "$status"
} >>"$LOG" 2>&1
