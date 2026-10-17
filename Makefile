# StockHub task runner. Requires GNU make, uv, pnpm (and dbmate from T3 on).
.DEFAULT_GOAL := help
SHELL := bash

PY  := cd py && uv run
WEB := cd web && pnpm

.PHONY: help db-up db-down db-local-init db-local-up db-local-down migrate migrate-status 	migrate-test db-new db-types py-install py-test py-fmt web-install web-dev web-check check

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
	@if ls db/migrations/*.sql >/dev/null 2>&1; then $(DBMATE) --wait up; 	else $(DBMATE) --wait status && echo "no migrations yet; database reachable"; fi

migrate-status: ## Show migration status
	$(DBMATE) status

migrate-test: ## Apply migrations to TEST_DATABASE_URL
	@if ls db/migrations/*.sql >/dev/null 2>&1; then $(DBMATE) --env TEST_DATABASE_URL --wait up; 	else $(DBMATE) --env TEST_DATABASE_URL --wait status; fi

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

web-install: ## Install web deps
	$(WEB) install --frozen-lockfile

web-dev: ## Next.js dev server
	$(WEB) dev

web-check: ## lint + typecheck + test
	$(WEB) check

check: py-test web-check ## Run all checks
