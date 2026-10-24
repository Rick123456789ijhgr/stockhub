"""Shared pytest fixtures.

Database tests run against TEST_DATABASE_URL (env var or the repo-root .env), which must
already be migrated (`make migrate-test`; `make py-test` does it for you).

- `pg` / `sa_conn`: a connection whose work is rolled back after the test.
- `clean_db`: an engine on freshly truncated tables, for code that commits on its own
  connections (RawStore, job runner).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator

import psycopg
import pytest
from sqlalchemy import Connection, Engine, text

from stockhub.common.db import make_engine
from stockhub.common.settings import PROJECT_ROOT

# Every table the app writes to; trading_calendar, financial_item_map and market_series keep
# their seeds (macro_events keeps its seeded rows, see clean_db).
MUTABLE_TABLES = (
    "stocks, prices_daily, corporate_actions, financials, monthly_revenue, "
    "raw_objects, job_runs, settings, audit_log, watchlist, portfolio_transactions, quotes_latest, "
    "quotes_intraday, "
    "prices_daily_quarantine, corporate_actions_quarantine, corporate_action_previews, "
    "dividend_receipts, alerts, financials_quarantine, financial_fetch_state, "
    "fundamentals_quarterly, fundamental_signals, job_requests, institutional_trades_daily, "
    "margin_daily, foreign_holdings_daily, shareholding_distribution, market_institutional_daily, "
    "market_margin_daily, chip_coverage, chip_quarantine, chip_summary, market_series_values, "
    "market_series_quarantine, themes, stock_themes, news_items, news_item_stocks, stock_aliases, "
    "llm_usage, sentiment_daily"
)
SEEDED_TABLES = ("news_sources", "llm_providers", "slang_terms")
"""M6 catalogs with seed rows that tests may change: restored to the migrated state."""


def _env_file_value(key: str) -> str | None:
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == key:
            return value.strip().strip("\"'") or None
    return None


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL") or _env_file_value("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set (env var or repo-root .env)")
    return url


@pytest.fixture(scope="session")
def pg_session_conn(test_database_url: str) -> Iterator[psycopg.Connection]:
    # autocommit: no implicit transaction lingers between tests holding table locks.
    with psycopg.connect(test_database_url, autocommit=True) as conn:
        migrated = conn.execute("SELECT to_regclass('public.job_runs') IS NOT NULL").fetchone()
        if not migrated or not migrated[0]:
            pytest.fail("test database is not migrated; run `make migrate-test`")
        yield conn


@pytest.fixture
def pg(pg_session_conn: psycopg.Connection) -> Iterator[psycopg.Connection]:
    """A psycopg connection whose work is rolled back after the test."""
    with pg_session_conn.transaction(force_rollback=True):
        yield pg_session_conn


@pytest.fixture(scope="session")
def engine(test_database_url: str, pg_session_conn: psycopg.Connection) -> Iterator[Engine]:
    eng = make_engine(test_database_url)
    yield eng
    eng.dispose()


@pytest.fixture
def sa_conn(engine: Engine) -> Iterator[Connection]:
    """A SQLAlchemy connection whose work is rolled back after the test."""
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()


@pytest.fixture(scope="session")
def seed_statements() -> list[str]:
    """The seed INSERTs of the M6 catalogs, read from the migration (not from the test
    database, which an earlier run may have left changed)."""
    out = []
    for migration in sorted((PROJECT_ROOT / "db" / "migrations").glob("*.sql")):
        up = migration.read_text(encoding="utf-8").split("-- migrate:down")[0]
        for table in SEEDED_TABLES:
            out += re.findall(rf"INSERT INTO {table} \(.*?\);\n", up, flags=re.S)
    return out


@pytest.fixture
def clean_db(engine: Engine, seed_statements: list[str]) -> Engine:
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {MUTABLE_TABLES} RESTART IDENTITY CASCADE"))
        conn.execute(text("DELETE FROM macro_events WHERE source <> 'seed'"))
        conn.execute(text(f"TRUNCATE {', '.join(SEEDED_TABLES)} RESTART IDENTITY CASCADE"))
        for statement in seed_statements:
            conn.exec_driver_sql(statement)
    return engine
