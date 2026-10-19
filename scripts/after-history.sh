#!/usr/bin/env bash
# One-off follow-up for an `make etl-history` started before derive_delisted_etfs and
# sync_dividend_details existed: waits until that run has finished (its last step,
# compute_adj_factors, ran after the backfill), then adds what the old recipe lacks.
# Usage: scripts/after-history.sh <backfill_prices job_runs id>   (log: .local/logs)
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKFILL_ID="${1:?usage: $0 <backfill_prices run id>}"
export PATH="$HOME/.local/bin:$PATH" PGPASSWORD=stockhub
PSQL="$(command -v psql || ls -d /c/Program\ Files/PostgreSQL/*/bin/psql.exe 2>/dev/null | sort -V | tail -1)"
mkdir -p "$ROOT/.local/logs"
LOG="$ROOT/.local/logs/after-history-$(date +%Y%m%d).log"

done_query="SELECT count(*) FROM job_runs WHERE job_name = 'compute_adj_factors'
  AND id > $BACKFILL_ID AND status <> 'running'"
{
  echo "=== $(date '+%F %T') waiting for etl-history (backfill run #$BACKFILL_ID)"
  for _ in $(seq 1 288); do # 5-minute checks, up to 24 h
    n="$("$PSQL" -h localhost -p 5433 -U stockhub -d stockhub -At -c "$done_query" 2>/dev/null)"
    [[ "${n:-0}" -gt 0 ]] && break
    sleep 300
  done
  [[ "${n:-0}" -gt 0 ]] || { echo "gave up waiting"; exit 1; }
} >>"$LOG" 2>&1

# Delisted ETFs first, so the event import can attach their dividends and splits.
"$ROOT/scripts/scheduled.sh" etl-etf-delistings &&
  "$ROOT/scripts/scheduled.sh" etl-corporate-actions start=2004-01-01 &&
  "$ROOT/scripts/scheduled.sh" etl-dividends start=2009-01-01 &&
  "$ROOT/scripts/scheduled.sh" etl-adjust
