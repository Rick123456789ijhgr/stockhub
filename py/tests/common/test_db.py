from __future__ import annotations

import pytest
from sqlalchemy import Connection, Engine, text

from stockhub.common.db import session_scope, sqlalchemy_url, upsert


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "postgresql://u:p@h:5433/db?sslmode=disable",
            "postgresql+psycopg://u:p@h:5433/db?sslmode=disable",
        ),
        ("postgres://u@h/db", "postgresql+psycopg://u@h/db"),
        ("postgresql+psycopg://u@h/db", "postgresql+psycopg://u@h/db"),
    ],
)
def test_sqlalchemy_url(url: str, expected: str) -> None:
    assert sqlalchemy_url(url) == expected


def test_sqlalchemy_url_rejects_other_schemes() -> None:
    with pytest.raises(ValueError, match="postgresql://"):
        sqlalchemy_url("mysql://u@h/db")


def test_upsert_is_idempotent(sa_conn: Connection) -> None:
    rows = [{"key": "fee_discount", "value": 0.28}, {"key": "tax_rate", "value": 0.003}]
    assert upsert(sa_conn, "settings", rows, ["key"]) == 2
    # Same values again: nothing is rewritten.
    assert upsert(sa_conn, "settings", rows, ["key"]) == 0
    # A changed value updates exactly one row.
    assert upsert(sa_conn, "settings", [{"key": "tax_rate", "value": 0.0015}], ["key"]) == 1
    count = sa_conn.execute(text("SELECT count(*) FROM settings")).scalar_one()
    value = sa_conn.execute(text("SELECT value FROM settings WHERE key = 'tax_rate'")).scalar_one()
    assert (count, value) == (2, 0.0015)


def test_upsert_do_nothing(sa_conn: Connection) -> None:
    upsert(sa_conn, "settings", [{"key": "k", "value": 1}], ["key"])
    assert upsert(sa_conn, "settings", [{"key": "k", "value": 2}], ["key"], update_cols=[]) == 0
    assert sa_conn.execute(text("SELECT value FROM settings")).scalar_one() == 1


def test_upsert_empty_rows(sa_conn: Connection) -> None:
    assert upsert(sa_conn, "settings", [], ["key"]) == 0


def test_session_scope_commits_or_rolls_back(clean_db: Engine) -> None:
    with session_scope(clean_db) as session:
        session.execute(text("INSERT INTO settings (key, value) VALUES ('a', '1')"))

    def failing_unit_of_work() -> None:
        with session_scope(clean_db) as session:
            session.execute(text("INSERT INTO settings (key, value) VALUES ('b', '1')"))
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        failing_unit_of_work()
    with clean_db.connect() as conn:
        keys = conn.execute(text("SELECT key FROM settings ORDER BY key")).scalars().all()
    assert keys == ["a"]
