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


def test_calendar_seed_covers_2004_and_delisting_columns_default(pg: psycopg.Connection) -> None:
    first = pg.execute("SELECT min(date) FROM trading_calendar").fetchone()
    assert first == (date(2004, 1, 1),)
    row = pg.execute(
        "INSERT INTO stocks (symbol, market, type, name, listed_date) "
        "VALUES ('T001', 'twse', 'stock', 'x', '2020-01-01') "
        "RETURNING listed_date_estimated, delisting_reason"
    ).fetchone()
    assert row == (False, None)


def test_corporate_action_price_factor_is_generated(pg: psycopg.Connection) -> None:
    stock = pg.execute(
        "INSERT INTO stocks (symbol, market, type, name, listed_date) "
        "VALUES ('T002', 'twse', 'etf', 'x', '2003-06-30') RETURNING id"
    ).fetchone()
    assert stock is not None
    factors = pg.execute(
        "INSERT INTO corporate_actions "
        "(stock_id, ex_date, action_type, prev_close, reference_price, ratio, source) VALUES "
        "(%(id)s, '2025-06-18', 'split', 188.65, 47.16, NULL, 't'), "
        "(%(id)s, '2025-07-01', 'split', NULL, NULL, 4, 't'), "
        "(%(id)s, '2025-08-01', 'cash_and_stock_dividend', NULL, NULL, NULL, 't') "
        "RETURNING price_factor",
        {"id": stock[0]},
    ).fetchall()
    assert factors == [(Decimal("0.2499867479"),), (Decimal("0.2500000000"),), (None,)]
    quarantine = pg.execute(
        "SELECT obj_description('corporate_actions_quarantine'::regclass, 'pg_class')"
    ).fetchone()
    assert quarantine is not None
    assert quarantine[0]


def test_prices_daily_coverage_follows_writes(pg: psycopg.Connection) -> None:
    # The pg fixture runs inside a rolled-back transaction, so start from a known state.
    pg.execute("DELETE FROM prices_daily")
    a, b = _insert_stock(pg, "2330"), _insert_stock(pg, "2317")

    def coverage() -> list[tuple[object, ...]]:
        return pg.execute(
            "SELECT trade_date::text, market, bars FROM prices_daily_coverage ORDER BY 1, 2"
        ).fetchall()

    upsert = (
        "INSERT INTO prices_daily (stock_id, trade_date, close, high, low, open, source) "
        "SELECT id, d, 10, 10, 10, 10, 'test' FROM unnest(%s::bigint[]) id, "
        "unnest(%s::date[]) d ON CONFLICT (stock_id, trade_date) DO UPDATE SET close = 11"
    )
    pg.execute(upsert, ([a, b], [date(2026, 10, 15), date(2026, 10, 16)]))
    assert coverage() == [("2026-10-15", "twse", 2), ("2026-10-16", "twse", 2)]
    pg.execute(upsert, ([a, b], [date(2026, 10, 16)]))  # updates only: counts unchanged
    assert coverage() == [("2026-10-15", "twse", 2), ("2026-10-16", "twse", 2)]

    pg.execute("UPDATE stocks SET market = 'tpex' WHERE id = %s", (b,))
    assert coverage() == [
        ("2026-10-15", "tpex", 1),
        ("2026-10-15", "twse", 1),
        ("2026-10-16", "tpex", 1),
        ("2026-10-16", "twse", 1),
    ]
    pg.execute("DELETE FROM prices_daily WHERE stock_id = %s", (b,))
    assert coverage() == [("2026-10-15", "twse", 1), ("2026-10-16", "twse", 1)]
    pg.execute("TRUNCATE prices_daily CASCADE")
    assert coverage() == []


def test_m2_portfolio_columns_and_watchlist_position(pg: psycopg.Connection) -> None:
    stock_id = _insert_stock(pg)
    row = pg.execute(
        "INSERT INTO portfolio_transactions (stock_id, trade_date, side, quantity, price) "
        "VALUES (%s, '2026-10-16', 'buy', 1000, 1000) "
        "RETURNING day_trade, fee_rebate, fee_manual, tax_manual",
        (stock_id,),
    ).fetchone()
    assert row == (False, Decimal("0.00"), False, False)
    _expect(
        pg,
        errors.CheckViolation,
        "UPDATE portfolio_transactions SET fee_rebate = -1 WHERE stock_id = %s",
        (stock_id,),
    )
    pg.execute("INSERT INTO watchlist (stock_id) VALUES (%s)", (stock_id,))
    position = pg.execute("SELECT position FROM watchlist WHERE stock_id = %s", (stock_id,))
    assert position.fetchone() == (0,)


def test_corporate_action_previews_key_and_checks(pg: psycopg.Connection) -> None:
    stock_id = _insert_stock(pg)
    sql = (
        "INSERT INTO corporate_action_previews (stock_id, ex_date, source, label, action_type, "
        "cash_dividend) VALUES (%s, '2026-10-22', 'twse', %s, 'cash_dividend', NULL)"
    )
    pg.execute(sql, (stock_id, "息"))
    row = pg.execute(
        "SELECT stock_dividend_ratio, rights_ratio FROM corporate_action_previews"
    ).fetchone()
    assert row == (Decimal(0), Decimal(0))
    _expect(pg, errors.UniqueViolation, sql, (stock_id, "息"))
    _expect(pg, errors.CheckViolation, sql.replace("'twse'", "'tpex'"), (stock_id, "除息"))


def test_dividend_receipts_need_an_amount(pg: psycopg.Connection) -> None:
    stock_id = _insert_stock(pg)
    sql = (
        "INSERT INTO dividend_receipts (stock_id, ex_date, action_type, cash, shares) "
        "VALUES (%s, '2026-07-01', 'cash_dividend', %s, %s)"
    )
    pg.execute(sql, (stock_id, Decimal("4320"), None))
    _expect(pg, errors.UniqueViolation, sql, (stock_id, Decimal("1"), None))
    _expect(pg, errors.CheckViolation, sql.replace("07-01", "08-01"), (stock_id, None, None))
