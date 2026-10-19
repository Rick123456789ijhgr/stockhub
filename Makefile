# StockHub task runner. Requires GNU make, uv, pnpm (and dbmate from T3 on).
.DEFAULT_GOAL := help
SHELL := bash

PY  := cd py && uv run
WEB := cd web && pnpm

.PHONY: help db-up db-down db-local-init db-local-up db-local-down migrate migrate-status \
	migrate-test db-new db-types py-install py-test py-fmt notify-test etl-list etl-heartbeat etl-daily \
	etl-backfill etl-history etl-adjust etl-previews etl-corporate-actions etl-dividends etl-etf-delistings etl-quotes \
	web-install web-dev web-build web-check check

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'

# dbmate reads DATABASE_URL from the environment or the root .env file.
DBMATE := dbmate --migrations-dir db/migrations --no-dump-schema

db-up: ## Start local Postgres via docker compose
	docker compose up -d --wait

db-down: ## Stop docker compose Postgres
	docker compose down

db-local-init: ## Docker-free: create a local cluster (needs Postgres binaries)
	scripts/local-pg.sh init

db-local-up: ## Docker-free: start the local cluster
	scripts/local-pg.sh start

db-local-down: ## Docker-free: stop the local cluster
	scripts/local-pg.sh stop

migrate: ## Apply db/migrations to DATABASE_URL (creates the database if missing)
	@if ls db/migrations/*.sql >/dev/null 2>&1; then \
		$(DBMATE) --wait up; \
	else $(DBMATE) --wait status && echo "no migrations yet; database reachable"; fi

migrate-status: ## Show migration status
	$(DBMATE) status

migrate-test: ## Apply migrations to TEST_DATABASE_URL
	@if ls db/migrations/*.sql >/dev/null 2>&1; then \
		$(DBMATE) --env TEST_DATABASE_URL --wait up; \
	else $(DBMATE) --env TEST_DATABASE_URL --wait status; fi

db-new: ## Create a migration: make db-new name=add_foo
	$(DBMATE) new $(name)

db-types: ## Regenerate web/src/lib/db/types.gen.ts from DATABASE_URL (run after migrate)
	$(WEB) db:types

py-install: ## Install Python deps (uv sync)
	cd py && uv sync

py-test: migrate-test ## ruff + mypy + pytest (migrates the test DB first)
	$(PY) ruff check
	$(PY) ruff format --check
	$(PY) mypy
	$(PY) pytest

py-fmt: ## Auto-fix and format Python code
	$(PY) ruff check --fix
	$(PY) ruff format

etl-list: ## List ETL jobs
	$(PY) python -m stockhub.etl list

notify-test: ## Send a test message through NOTIFIER (console or email) to check SMTP settings
	$(PY) python -m stockhub.etl notify-test

etl-heartbeat: ## Run the heartbeat job against DATABASE_URL
	$(PY) python -m stockhub.etl run heartbeat

# Optional overrides: make etl-daily date=2026-10-16 / make etl-backfill start=2025-10-17 end=2026-10-16
ETL := $(PY) python -m stockhub.etl run

etl-daily: ## Update calendar, stock master, delistings and the day's prices (date=YYYY-MM-DD)
	$(ETL) sync_calendar
	$(ETL) sync_stocks
	$(ETL) sync_delistings
	$(ETL) sync_corporate_actions
	$(ETL) sync_dividend_details
	$(ETL) sync_ex_rights_previews
	$(ETL) daily_prices $(if $(date),--date $(date))
	$(ETL) compute_adj_factors
	$(ETL) check_holding_alerts

etl-corporate-actions: ## Ex-rights/dividends, reductions, splits for [start, end] (default past 30 days)
	$(ETL) sync_corporate_actions $(if $(start),--param start=$(start)) $(if $(end),--param end=$(end))

etl-dividends: ## Cash/stock parts of TWSE 權息 events (start= end=; default past 30 days; ~5 s per event)
	$(ETL) sync_dividend_details $(if $(start),--param start=$(start)) $(if $(end),--param end=$(end))

etl-etf-delistings: ## Delisted ETFs + their bars from stored daily tables (no network; after backfills)
	$(ETL) derive_delisted_etfs $(if $(dry_run),--param dry_run=true)

etl-adjust: ## Recompute adj_factor (e.g. after confirming price gaps on /admin)
	$(ETL) compute_adj_factors

etl-backfill: ## Daily prices for [start, end] (default: the past 365 days); resumable
	$(ETL) backfill_prices $(if $(start),--param start=$(start)) $(if $(end),--param end=$(end))

etl-quotes: ## Refresh ex-rights previews, then poll quotes for watchlist + holdings every 30 s until 13:35 (symbols=2330,0050 adds more)
	-$(ETL) sync_ex_rights_previews
	$(ETL) poll_quotes $(if $(symbols),--param symbols=$(symbols)) $(if $(once),--param once=true)

etl-previews: ## Upcoming ex-rights/dividend announcements (除權除息預告表) of both exchanges
	$(ETL) sync_ex_rights_previews

HISTORY_START := 2004-02-11

etl-history: ## Full history: delistings, prices since 2004-02-11, corporate actions (~6 h; resumable)
	$(ETL) sync_delistings --param start_year=2001
	$(ETL) backfill_prices --param start=$(HISTORY_START) $(if $(end),--param end=$(end))
	$(ETL) derive_delisted_etfs
	$(ETL) sync_delistings
	$(ETL) sync_corporate_actions --param start=2004-01-01 $(if $(end),--param end=$(end))
	$(ETL) compute_adj_factors
	$(ETL) sync_dividend_details --param start=2009-01-01 $(if $(end),--param end=$(end))

web-install: ## Install web deps
	$(WEB) install --frozen-lockfile

web-dev: ## Next.js dev server
	$(WEB) dev

web-build: ## Production build of the web app
	$(WEB) build

web-check: ## lint + typecheck + test
	$(WEB) check

check: py-test web-check ## Run all checks
