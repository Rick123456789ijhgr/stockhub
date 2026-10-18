"""Schema guarantees from db/migrations: keys, defaults and checks the app relies on."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import psycopg
import pytest
from psycopg import errors

M0_TABLES = {
    "trading_calendar",
    "stocks",
    "prices_daily",
    "corporate_actions",
    "financial_item_map",
    "financials",
    "monthly_revenue",
    "raw_objects",
    "job_runs",
    "settings",
    "audit_log",
    "watchlist",
    "portfolio_transactions",
}


def _insert_stock(pg: psycopg.Connection, symbol: str = "2330") -> int:
    row = pg.execute(
        "INSERT INTO stocks (symbol, market, type, name, listed_date) "
        "VALUES (%s, 'twse', 'stock', 'TSMC', '1994-09-05') RETURNING id",
        (symbol,),
    ).fetchone()
    assert row
    return int(row[0])


def _expect(
    pg: psycopg.Connection, exc: type[Exception], sql: str, params: tuple[object, ...] = ()
) -> None:
    with pytest.raises(exc), pg.transaction():
        pg.execute(sql, params)


def test_all_m0_tables_exist_and_are_commented(pg: psycopg.Connection) -> None:
    rows = pg.execute(
        "SELECT c.relname, obj_description(c.oid, 'pg_class') FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind = 'r'"
    ).fetchall()
    comments: dict[str, str | None] = dict(rows)
    assert comments.keys() >= M0_TABLES
    assert all(comments[t] for t in M0_TABLES), "every table needs COMMENT ON TABLE"


def test_no_float_columns_and_timestamps_are_tz(pg: psycopg.Connection) -> None:
    bad = pg.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND data_type IN "
        "('real', 'double precision', 'timestamp without time zone')"
    ).fetchall()
    assert bad == []


def test_prices_daily_defaults_and_unique_key(pg: psycopg.Connection) -> None:
    stock_id = _insert_stock(pg)
    sql = (
        "INSERT INTO prices_daily (stock_id, trade_date, open, high, low, close, volume, source) "
        "VALUES (%s, '2026-10-16', 1000, 1010, 990, 1005, 1000, 'test')"
    )
    pg.execute(sql, (stock_id,))
    row = pg.execute("SELECT adj_factor FROM prices_daily WHERE stock_id = %s", (stock_id,))
    assert row.fetchone() == (Decimal("1.0000000000"),)
    _expect(pg, errors.UniqueViolation, sql, (stock_id,))


def test_prices_daily_rejects_inverted_range(pg: psycopg.Connection) -> None:
    stock_id = _insert_stock(pg)
    _expect(
        pg,
        errors.CheckViolation,
        "INSERT INTO prices_daily (stock_id, trade_date, high, low, source) "
        "VALUES (%s, '2026-10-16', 90, 100, 'test')",
        (stock_id,),
    )


def test_portfolio_quantity_must_be_positive(pg: psycopg.Connection) -> None:
    stock_id = _insert_stock(pg)
    sql = (
        "INSERT INTO portfolio_transactions (stock_id, trade_date, side, quantity, price) "
        "VALUES (%s, '2026-10-16', 'buy', %s, 1000)"
    )
    pg.execute(sql, (stock_id, 1000))
    _expect(pg, errors.CheckViolation, sql, (stock_id, 0))
    _expect(pg, errors.CheckViolation, sql, (stock_id, -1000))


def test_stocks_natural_key_allows_symbol_reuse_after_delisting(pg: psycopg.Connection) -> None:
    _insert_stock(pg, "9999")
    # Same symbol + listing date is a duplicate.
    _expect(
        pg,
        errors.UniqueViolation,
        "INSERT INTO stocks (symbol, market, type, name, listed_date) "
        "VALUES ('9999', 'twse', 'stock', 'dup', '1994-09-05')",
    )
    # A second active listing of the same symbol is rejected...
    _expect(
        pg,
        errors.UniqueViolation,
        "INSERT INTO stocks (symbol, market, type, name, listed_date) "
        "VALUES ('9999', 'tpex', 'stock', 'new', '2020-01-02')",
    )
    # ...but allowed once the old listing is delisted.
    pg.execute("UPDATE stocks SET delisted_date = '2019-12-31' WHERE symbol = '9999'")
    pg.execute(
        "INSERT INTO stocks (symbol, market, type, name, listed_date) "
        "VALUES ('9999', 'tpex', 'stock', 'new', '2020-01-02')"
    )


def test_financials_revision_default_and_natural_key(pg: psycopg.Connection) -> None:
    stock_id = _insert_stock(pg)
    sql = (
        "INSERT INTO financials (stock_id, period_end, period_type, statement, item_code, "
        "value, source, revision) VALUES (%s, '2026-06-30', 'Q', 'IS', 'Revenue', 1, 'test', %s)"
    )
    pg.execute(
        "INSERT INTO financials (stock_id, period_end, period_type, statement, item_code, "
        "value, source) VALUES (%s, '2026-06-30', 'Q', 'IS', 'Revenue', 1, 'test')",
        (stock_id,),
    )
    row = pg.execute("SELECT revision, publish_date FROM financials").fetchone()
    assert row == (0, None)
    _expect(pg, errors.UniqueViolation, sql, (stock_id, 0))
    pg.execute(sql, (stock_id, 1))  # a restatement is a new revision


def test_raw_objects_deduplicated_by_sha256(pg: psycopg.Connection) -> None:
    sql = (
        "INSERT INTO raw_objects (provider, dataset, uri, sha256, bytes) "
        "VALUES ('fake', 'prices', 'file:///x', %s, 2)"
    )
    pg.execute(sql, ("a" * 64,))
    _expect(pg, errors.UniqueViolation, sql, ("a" * 64,))
    _expect(pg, errors.CheckViolation, sql, ("NOT-A-HASH".ljust(64, "0"),))


def test_job_runs_single_running_instance_per_params(pg: psycopg.Connection) -> None:
    sql = "INSERT INTO job_runs (job_name, params, \"trigger\") VALUES ('j', %s, 'manual')"
    pg.execute(sql, ('{"date": "2026-10-16", "x": 1}',))
    # jsonb equality ignores key order.
    _expect(pg, errors.UniqueViolation, sql, ('{"x": 1, "date": "2026-10-16"}',))
    pg.execute(sql, ('{"date": "2026-10-17"}',))
    # finished_at must be set exactly when the run is no longer running.
    _expect(
        pg,
        errors.CheckViolation,
        "UPDATE job_runs SET status = 'succeeded' WHERE job_name = 'j'",
    )


def test_updated_at_trigger(pg: psycopg.Connection) -> None:
    pg.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES ('k', '1', '2000-01-01T00:00Z')"
    )
    pg.execute("UPDATE settings SET value = '2' WHERE key = 'k'")
    row = pg.execute("SELECT updated_at > '2000-01-02T00:00Z' FROM settings").fetchone()
    assert row == (True,)


def test_trading_calendar_weekday_seed(pg: psycopg.Connection) -> None:
    rows: dict[date, bool] = dict(
        pg.execute(
            "SELECT date, is_trading_day FROM trading_calendar "
            "WHERE date BETWEEN '2026-10-16' AND '2026-10-18'"
        ).fetchall()
    )
    assert rows == {date(2026, 10, 16): True, date(2026, 10, 17): False, date(2026, 10, 18): False}
