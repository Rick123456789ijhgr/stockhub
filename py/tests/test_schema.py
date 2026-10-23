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
        "value, basis, source, revision) "
        "VALUES (%s, '2026-06-30', 'Q', 'IS', 'Revenue', 1, 'ytd', %s, %s)"
    )
    pg.execute(
        "INSERT INTO financials (stock_id, period_end, period_type, statement, item_code, "
        "value, basis, source) VALUES (%s, '2026-06-30', 'Q', 'IS', 'Revenue', 1, 'ytd', 'twse')",
        (stock_id,),
    )
    row = pg.execute("SELECT revision, publish_date FROM financials").fetchone()
    assert row == (0, None)
    _expect(pg, errors.UniqueViolation, sql, (stock_id, "twse", 0))
    pg.execute(sql, (stock_id, "twse", 1))  # a changed value is a new revision
    pg.execute(sql, (stock_id, "finmind", 0))  # each source keeps its own rows
    _expect(pg, errors.CheckViolation, sql.replace("'ytd'", "'annual'"), (stock_id, "x", 0))


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


def test_general_item_map_is_seeded(pg: psycopg.Connection) -> None:
    rows: dict[str, str] = dict(
        pg.execute(
            "SELECT item_code, statement FROM financial_item_map WHERE industry_type = 'general'"
        ).fetchall()
    )
    assert rows["Revenue"] == "IS"
    assert rows["EquityParent"] == "BS"
    assert rows["OperatingCashFlow"] == "CF"


def test_financials_quarantine_resolution_pairs(pg: psycopg.Connection) -> None:
    stock_id = _insert_stock(pg)
    sql = (
        "INSERT INTO financials_quarantine (stock_id, period_end, statement, source, payload, "
        "reasons, resolved_at, resolution) VALUES (%s, '2026-06-30', 'IS', %s, '[]', %s, %s, %s)"
    )
    pg.execute(sql, (stock_id, "finmind", ["ytd_as_quarter"], None, None))
    _expect(pg, errors.UniqueViolation, sql, (stock_id, "finmind", ["x"], None, None))
    _expect(pg, errors.CheckViolation, sql, (stock_id, "twse", [], None, None))
    _expect(pg, errors.CheckViolation, sql, (stock_id, "twse", ["x"], None, "accepted"))


def test_monthly_revenue_growth_view(pg: psycopg.Connection) -> None:
    stock_id = _insert_stock(pg)
    for month, revenue in [
        ("2025-01-01", 100),
        ("2025-02-01", 100),
        ("2026-01-01", 110),
        ("2026-02-01", 132),
    ]:
        pg.execute(
            "INSERT INTO monthly_revenue (stock_id, revenue_month, revenue, source) "
            "VALUES (%s, %s, %s, 'test')",
            (stock_id, month, revenue),
        )
    row = pg.execute(
        "SELECT mom, yoy, ytd_revenue, ytd_yoy FROM monthly_revenue_growth "
        "WHERE stock_id = %s AND revenue_month = '2026-02-01'",
        (stock_id,),
    ).fetchone()
    assert row is not None
    mom, yoy, ytd, ytd_yoy = row
    assert round(mom, 6) == Decimal("0.2")
    assert round(yoy, 6) == Decimal("0.32")
    assert ytd == 242
    assert round(ytd_yoy, 6) == Decimal("0.21")

    # No December 2025, so January 2026 has no month-over-month figure.
    row = pg.execute(
        "SELECT prev_month_revenue, mom, last_year_revenue FROM monthly_revenue_growth "
        "WHERE stock_id = %s AND revenue_month = '2026-01-01'",
        (stock_id,),
    ).fetchone()
    assert row == (None, None, 100)


def test_monthly_revenue_growth_filters_by_index(pg: psycopg.Connection) -> None:
    # The stock_id filter must reach monthly_revenue (D-095); a full scan per lookup made
    # the peer table take seconds.
    pg.execute("SET LOCAL enable_seqscan = off")
    plan = "\n".join(
        r[0]
        for r in pg.execute(
            "EXPLAIN SELECT yoy FROM monthly_revenue_growth WHERE stock_id = 1"
        ).fetchall()
    )
    assert "monthly_revenue_pkey" in plan


def test_financials_official_period_index(pg: psycopg.Connection) -> None:
    pg.execute("SET LOCAL enable_seqscan = off")
    plan = "\n".join(
        r[0]
        for r in pg.execute(
            "EXPLAIN SELECT max(period_end) FROM financials WHERE source IN ('twse', 'tpex')"
        ).fetchall()
    )
    assert "financials_official_period_idx" in plan


CHIP_TABLES = {
    "institutional_trades_daily",
    "margin_daily",
    "foreign_holdings_daily",
    "shareholding_distribution",
    "market_institutional_daily",
    "market_margin_daily",
    "chip_coverage",
    "chip_quarantine",
    "chip_summary",
}


def test_chip_tables_and_columns_are_commented(pg: psycopg.Connection) -> None:
    rows = pg.execute(
        "SELECT c.relname, obj_description(c.oid, 'pg_class') FROM pg_class c "
        "WHERE c.relname = ANY(%s)",
        (list(CHIP_TABLES),),
    ).fetchall()
    assert {name for name, comment in rows if comment} == CHIP_TABLES


def test_institutional_trades_key_and_checks(pg: psycopg.Connection) -> None:
    stock_id = _insert_stock(pg)
    sql = (
        "INSERT INTO institutional_trades_daily (stock_id, trade_date, foreign_buy, "
        "foreign_sell, foreign_net, trust_buy, trust_sell, trust_net, dealer_buy, dealer_sell, "
        "dealer_net, total_net, source) VALUES (%s, '2026-10-16', %s, 0, %s, 0, 0, 0, 0, 0, 0, "
        "%s, 'twse')"
    )
    pg.execute(sql, (stock_id, 1000, 1000, 1000))
    row = pg.execute(
        "SELECT foreign_dealer_net, dealer_self_net FROM institutional_trades_daily"
    ).fetchone()
    assert row == (None, None)  # unsplit history stays NULL, not 0
    _expect(pg, errors.UniqueViolation, sql, (stock_id, 1000, 1000, 1000))
    _expect(pg, errors.CheckViolation, sql.replace("10-16", "10-15"), (stock_id, -1, -1, -1))


def test_margin_and_holdings_checks(pg: psycopg.Connection) -> None:
    stock_id = _insert_stock(pg)
    margin = (
        "INSERT INTO margin_daily (stock_id, trade_date, margin_buy, margin_sell, margin_redeem, "
        "margin_balance, short_sell, short_cover, short_redeem, short_balance, source) "
        "VALUES (%s, '2026-10-16', 0, 0, 0, %s, 0, 0, 0, 0, 'twse')"
    )
    pg.execute(margin, (stock_id, 5000))
    assert pg.execute("SELECT offset_shares FROM margin_daily").fetchone() == (0,)
    _expect(pg, errors.CheckViolation, margin.replace("10-16", "10-15"), (stock_id, -1))
    holdings = (
        "INSERT INTO foreign_holdings_daily (stock_id, trade_date, issued_shares, "
        "foreign_shares, foreign_ratio, source) VALUES (%s, '2026-10-16', 100, 70, %s, 'twse')"
    )
    pg.execute(holdings, (stock_id, Decimal("0.7")))
    _expect(pg, errors.CheckViolation, holdings.replace("10-16", "10-15"), (stock_id, Decimal(70)))


def test_distribution_levels_and_market_tables(pg: psycopg.Connection) -> None:
    stock_id = _insert_stock(pg)
    sql = (
        "INSERT INTO shareholding_distribution (stock_id, week_date, level, holders, shares, "
        "ratio, source) VALUES (%s, '2026-10-16', %s, 0, %s, 0, 'tdcc')"
    )
    pg.execute(sql, (stock_id, 16, -5))  # the adjustment bracket may be negative
    _expect(pg, errors.CheckViolation, sql, (stock_id, 18, 0))
    market = (
        "INSERT INTO market_institutional_daily (market, trade_date, investor, buy_amount, "
        "sell_amount, net_amount, source) VALUES ('twse', '2026-10-16', %s, 1, 2, -1, 'twse')"
    )
    pg.execute(market, ("foreign",))
    _expect(pg, errors.CheckViolation, market, ("retail",))


def test_chip_coverage_and_quarantine(pg: psycopg.Connection) -> None:
    stock_id = _insert_stock(pg)
    cover = (
        "INSERT INTO chip_coverage (dataset, market, trade_date, rows, source) "
        "VALUES (%s, %s, '2026-10-16', 0, 'twse')"
    )
    pg.execute(cover, ("margin", "twse"))
    _expect(pg, errors.UniqueViolation, cover, ("margin", "twse"))
    _expect(pg, errors.CheckViolation, cover, ("prices", "twse"))
    quarantine = (
        "INSERT INTO chip_quarantine (dataset, stock_id, trade_date, source, payload, reasons, "
        "resolved_at, resolution) VALUES ('margin', %s, '2026-10-16', 'twse', '{}', %s, %s, %s)"
    )
    pg.execute(quarantine, (stock_id, ["margin_balance_mismatch"], None, None))
    _expect(pg, errors.UniqueViolation, quarantine, (stock_id, ["x"], None, None))
    _expect(
        pg,
        errors.CheckViolation,
        quarantine.replace("'margin'", "'institutional'"),
        (stock_id, ["x"], None, "accepted"),
    )


def test_m4_alert_kind_and_job_request(pg: psycopg.Connection) -> None:
    stock_id = _insert_stock(pg)
    pg.execute(
        "INSERT INTO alerts (kind, stock_id, trade_date, severity, title) "
        "VALUES ('institutional_flow', %s, '2026-10-16', 'warning', 't')",
        (stock_id,),
    )
    pg.execute(
        "INSERT INTO job_requests (job_name, requested_by) VALUES ('sync_chips', 'me@example.com')"
    )


def test_shareholding_concentration_matches_engine(pg: psycopg.Connection) -> None:
    from stockhub.engine.chips import BIG_HOLDER_LEVELS, WHALE_LEVEL, holder_ratio

    stock_id = _insert_stock(pg)
    week = {1: (900, 1_000), 11: (10, 3_000), 12: (5, 2_500), 15: (2, 40_000), 16: (1, 7)}
    week[17] = (918, 46_507)
    for level, (holders, shares) in week.items():
        pg.execute(
            "INSERT INTO shareholding_distribution (stock_id, week_date, level, holders, shares, "
            "ratio, source) VALUES (%s, '2026-10-16', %s, %s, %s, 0, 'test')",
            (stock_id, level, holders, shares),
        )
    row = pg.execute(
        "SELECT big_holder_ratio, whale_ratio, big_holders, holders "
        "FROM shareholding_concentration WHERE stock_id = %s",
        (stock_id,),
    ).fetchone()
    assert row is not None
    by_level = {level: s for level, (_, s) in week.items()}
    assert float(row[0]) == pytest.approx(holder_ratio(by_level, BIG_HOLDER_LEVELS))
    assert float(row[1]) == pytest.approx(holder_ratio(by_level, [WHALE_LEVEL]))
    assert (row[2], row[3]) == (7, 918)


M5_TABLES = {
    "market_series",
    "market_series_values",
    "market_series_status",
    "market_series_quarantine",
    "themes",
    "stock_themes",
    "macro_events",
}


def test_m5_tables_are_commented_and_seeded(pg: psycopg.Connection) -> None:
    rows = pg.execute(
        "SELECT c.relname, obj_description(c.oid, 'pg_class') FROM pg_class c "
        "WHERE c.relname = ANY(%s)",
        (list(M5_TABLES),),
    ).fetchall()
    assert {name for name, comment in rows if comment} == M5_TABLES
    codes = {r[0] for r in pg.execute("SELECT code FROM market_series").fetchall()}
    assert {"TAIEX", "TPEX", "SPX", "SOX", "USDTWD", "UST10Y", "TW_SIGNAL"} <= codes
    fomc = pg.execute("SELECT count(*) FROM macro_events WHERE kind = 'fomc'").fetchone()
    assert fomc == (8,)


def test_market_series_values_key_checks_and_status(pg: psycopg.Connection) -> None:
    sql = (
        "INSERT INTO market_series_values (series_code, obs_date, high, low, value, source) "
        "VALUES (%s, %s, %s, %s, %s, 'test')"
    )
    pg.execute(sql, ("TAIEX", "2026-10-16", 100, 90, 95))
    pg.execute(sql, ("TAIEX", "2026-10-19", None, None, 96))
    _expect(pg, errors.UniqueViolation, sql, ("TAIEX", "2026-10-16", None, None, 1))
    _expect(pg, errors.CheckViolation, sql, ("TAIEX", "2026-10-20", 90, 100, 95))
    _expect(pg, errors.ForeignKeyViolation, sql, ("NOPE", "2026-10-20", None, None, 1))
    row = pg.execute(
        "SELECT first_date, last_date, observations FROM market_series_status WHERE code = 'TAIEX'"
    ).fetchone()
    assert row == (date(2026, 10, 16), date(2026, 10, 19), 2)
    empty = pg.execute(
        "SELECT last_date, observations FROM market_series_status WHERE code = 'SPX'"
    ).fetchone()
    assert empty == (None, 0)


def test_market_series_quarantine_resolution_pairs(pg: psycopg.Connection) -> None:
    sql = (
        "INSERT INTO market_series_quarantine (series_code, obs_date, source, payload, reasons, "
        "resolved_at, resolution) VALUES ('SPX', '2026-10-16', 'yahoo', '{}', %s, %s, %s)"
    )
    _expect(pg, errors.CheckViolation, sql, ([], None, None))
    _expect(pg, errors.CheckViolation, sql, (["x"], None, "accepted"))
    pg.execute(sql, (["move_too_large"], None, None))


def test_stock_themes_period_and_cascade(pg: psycopg.Connection) -> None:
    stock_id = _insert_stock(pg)
    row = pg.execute("INSERT INTO themes (name) VALUES ('AI 伺服器') RETURNING id").fetchone()
    assert row
    theme_id = row[0]
    _expect(pg, errors.UniqueViolation, "INSERT INTO themes (name) VALUES ('AI 伺服器')")
    _expect(pg, errors.CheckViolation, "INSERT INTO themes (name) VALUES ('  ')")
    sql = (
        "INSERT INTO stock_themes (theme_id, stock_id, valid_from, valid_to) "
        "VALUES (%s, %s, %s, %s)"
    )
    _expect(pg, errors.CheckViolation, sql, (theme_id, stock_id, "2026-10-01", "2026-09-30"))
    pg.execute(sql, (theme_id, stock_id, "2026-01-01", None))
    pg.execute("DELETE FROM themes WHERE id = %s", (theme_id,))
    assert pg.execute("SELECT count(*) FROM stock_themes").fetchone() == (0,)


def test_m5_macro_alerts_have_no_stock_and_share_a_cooldown(pg: psycopg.Connection) -> None:
    stock_id = _insert_stock(pg)
    sql = (
        "INSERT INTO alerts (kind, stock_id, trade_date, severity, title) "
        "VALUES (%s, %s, '2026-08-01', 'warning', 't')"
    )
    pg.execute(sql, ("business_signal", None))
    _expect(pg, errors.UniqueViolation, sql, ("business_signal", None))
    _expect(pg, errors.CheckViolation, sql, ("policy_rate", stock_id))
    _expect(pg, errors.CheckViolation, sql, ("holding_move", None))
    pg.execute(sql, ("holding_move", stock_id))
    _expect(
        pg,
        errors.UniqueViolation,
        "INSERT INTO macro_events (event_date, kind, title, source) "
        "VALUES ('2026-10-28', 'fomc', 'FOMC 利率決策', 'manual')",
    )
    for job in ("sync_markets", "sync_macro"):
        pg.execute(
            "INSERT INTO job_requests (job_name, requested_by) VALUES (%s, 'me@example.com')",
            (job,),
        )


def test_per_stock_tables_cluster_by_stock(pg: psycopg.Connection) -> None:
    # `make db-cluster` runs a plain CLUSTER, which only rewrites tables marked here (D-117).
    rows = pg.execute(
        """
        SELECT c.relname, a.attname
        FROM pg_index x
        JOIN pg_class c ON c.oid = x.indrelid
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = x.indkey[0]
        WHERE x.indisclustered
        """
    ).fetchall()
    clustered: dict[str, str] = {r[0]: r[1] for r in rows}
    for table in (
        "prices_daily",
        "institutional_trades_daily",
        "margin_daily",
        "foreign_holdings_daily",
        "financials",
        "fundamentals_quarterly",
        "fundamental_signals",
        "monthly_revenue",
        "quotes_intraday",
    ):
        assert clustered.get(table) == "stock_id", table


def test_quotes_intraday_key_checks_and_comments(pg: psycopg.Connection) -> None:
    stock = _insert_stock(pg)
    sql = (
        "INSERT INTO quotes_intraday (stock_id, sampled_at, trade_date, quote_time, price, "
        "volume, source) VALUES (%s, %s, '2026-10-16', '2026-10-16 01:00:00+00', %s, %s, 'test')"
    )
    pg.execute(sql, (stock, "2026-10-16 01:00:30+00", 100, 1000))
    _expect(pg, errors.UniqueViolation, sql, (stock, "2026-10-16 01:00:30+00", 101, 1000))
    _expect(pg, errors.CheckViolation, sql, (stock, "2026-10-16 01:01:00+00", 0, 1000))
    _expect(pg, errors.NotNullViolation, sql, (stock, "2026-10-16 01:01:00+00", None, 1000))
    comment = pg.execute("SELECT obj_description('quotes_intraday'::regclass)").fetchone()
    assert comment
    assert comment[0]
