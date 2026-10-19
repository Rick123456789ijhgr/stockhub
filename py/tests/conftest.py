"""Shared pytest fixtures.

Database tests run against TEST_DATABASE_URL (env var or the repo-root .env), which must
already be migrated (`make migrate-test`; `make py-test` does it for you).

- `pg` / `sa_conn`: a connection whose work is rolled back after the test.
- `clean_db`: an engine on freshly truncated tables, for code that commits on its own
  connections (RawStore, job runner).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest
from sqlalchemy import Connection, Engine, text

from stockhub.common.db import make_engine
from stockhub.common.settings import PROJECT_ROOT

# Every table the app writes to; trading_calendar keeps its migration seed.
MUTABLE_TABLES = (
    "stocks, prices_daily, corporate_actions, financial_item_map, financials, monthly_revenue, "
    "raw_objects, job_runs, settings, audit_log, watchlist, portfolio_transactions, quotes_latest, "
    "prices_daily_quarantine, corporate_actions_quarantine, corporate_action_previews, "
    "dividend_receipts, alerts"
)


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


@pytest.fixture
def clean_db(engine: Engine) -> Engine:
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {MUTABLE_TABLES} RESTART IDENTITY CASCADE"))
    return engine
