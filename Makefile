# StockHub task runner. Requires GNU make, uv, pnpm (and dbmate from T3 on).
.DEFAULT_GOAL := help
SHELL := bash

PY  := cd py && uv run
WEB := cd web && pnpm

.PHONY: help py-install py-test py-fmt web-install web-dev web-check check

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'

py-install: ## Install Python deps (uv sync)
	cd py && uv sync

py-test: ## ruff + mypy + pytest
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
