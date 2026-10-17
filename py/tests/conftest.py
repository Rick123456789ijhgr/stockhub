"""Shared pytest fixtures.

Database tests run against TEST_DATABASE_URL (env var or the repo-root .env), which must
already be migrated (`make migrate-test`; `make py-test` does it for you). Each test runs
inside a transaction that is rolled back, so tests never see each other's rows.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_file_value(key: str) -> str | None:
    env_file = REPO_ROOT / ".env"
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
    with psycopg.connect(test_database_url) as conn:
        migrated = conn.execute("SELECT to_regclass('public.job_runs') IS NOT NULL").fetchone()
        if not migrated or not migrated[0]:
            pytest.fail("test database is not migrated; run `make migrate-test`")
        yield conn


@pytest.fixture
def pg(pg_session_conn: psycopg.Connection) -> Iterator[psycopg.Connection]:
    """A psycopg connection whose work is rolled back after the test."""
    with pg_session_conn.transaction(force_rollback=True):
        yield pg_session_conn
