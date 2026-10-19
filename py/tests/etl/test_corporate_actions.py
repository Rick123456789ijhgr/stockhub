"""Corporate action parsers, import job and adj_factor computation (no network)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, text

from stockhub.common.notifier import ConsoleNotifier
from stockhub.common.rawstore import LocalRawStore
from stockhub.etl.jobs.base import JobRunResult, run_job
from stockhub.etl.jobs.corporate_actions import (
    store_corporate_actions,
    year_chunks,
)
from stockhub.etl.providers.base import CorporateAction, DividendDetail
from stockhub.etl.providers.http import make_client
from stockhub.etl.providers.tpex import TpexProvider
from stockhub.etl.providers.tpex import _dividend_row as tpex_dividend_row
from stockhub.etl.providers.twse import TwseProvider
from stockhub.etl.quality import check_corporate_action, check_dividend_detail

from .official_sources import official_handler, official_router

D = Decimal
YEAR_2025 = (date(2025, 1, 1), date(2025, 12, 31))


def _providers() -> tuple[TwseProvider, TpexProvider]:
    client = make_client(httpx.MockTransport(official_handler))
    return TwseProvider(client), TpexProvider(client)


def _by_symbol(actions: list[CorporateAction]) -> dict[str, CorporateAction]:
    return {a.symbol: a for a in actions}


# ----------------------------------------------------------------------------- parsers


def test_twse_dividends_current_format() -> None:
    twse, _ = _providers()
    raw = twse.fetch_corporate_actions("twse", "dividend", *YEAR_2025)
    actions = _by_symbol(twse.parse_corporate_actions(raw))
    assert set(actions) == {"1598", "3543", "6423", "1605", "00939"}
    cash = actions["1598"]
    assert (cash.ex_date, cash.action_type, cash.cash_dividend) == (
        date(2025, 6, 2),
        "cash_dividend",
        D("0.500000"),
    )
    assert (cash.prev_close, cash.reference_price) == (D("22.70"), D("22.20"))
    # Since ~2010 only the total is published: no cash figure for 權息, none for 權.
    assert actions["1605"].action_type == "cash_and_stock_dividend"
    assert actions["1605"].cash_dividend is None
    assert actions["6423"].action_type == "stock_dividend"
    assert actions["6423"].cash_dividend is None
    assert actions["00939"].action_type == "cash_dividend"


def test_twse_dividends_2004_format_splits_cash_and_numbers_are_floats() -> None:
    twse, _ = _providers()
    raw = twse.fetch_corporate_actions("twse", "dividend", date(2004, 1, 1), date(2004, 12, 31))
    actions = _by_symbol(twse.parse_corporate_actions(raw))
    assert set(actions) == {"1227", "2849"}  # 9103 is a TDR: out of scope
    assert actions["1227"].cash_dividend == D("0.5")
    assert actions["1227"].ex_date == date(2004, 1, 13)
    assert actions["2849"].action_type == "stock_dividend"


def test_twse_resumption_tables() -> None:
    twse, _ = _providers()
    reductions = _by_symbol(
        twse.parse_corporate_actions(
            twse.fetch_corporate_actions("twse", "capital_reduction", *YEAR_2025)
        )
    )
    assert reductions["2025"].action_type == "capital_reduction"
    assert (reductions["2025"].prev_close, reductions["2025"].reference_price) == (
        D("10.50"),
        D("17.09"),
    )
    par = _by_symbol(
        twse.parse_corporate_actions(
            twse.fetch_corporate_actions("twse", "par_value_change", *YEAR_2025)
        )
    )
    assert par["6919"].action_type == "split"
    assert par["6919"].prev_close == D("1215.00")  # thousands separator
    splits = _by_symbol(
        twse.parse_corporate_actions(twse.fetch_corporate_actions("twse", "etf_split", *YEAR_2025))
    )
    assert splits["0050"].ex_date == date(2025, 6, 18)
    assert splits["0050"].action_type == "split"
    assert splits["00676R"].action_type == "reverse_split"


def test_twse_empty_table() -> None:
    twse, _ = _providers()
    raw = twse.fetch_corporate_actions("twse", "etf_split", date(2019, 1, 1), date(2019, 12, 31))
    assert twse.parse_corporate_actions(raw) == []


def test_tpex_dividends_have_exact_cash_and_stock_parts() -> None:
    _, tpex = _providers()
    raw = tpex.fetch_corporate_actions("tpex", "dividend", *YEAR_2025)
    actions = _by_symbol(tpex.parse_corporate_actions(raw))
    assert set(actions) == {"6788", "00950B", "6712", "6762"}
    both = actions["6762"]
    assert both.action_type == "cash_and_stock_dividend"
    assert both.cash_dividend == D("0.30000000")
    assert both.stock_dividend_ratio == D("0.15000000327")
    assert actions["6712"].cash_dividend == 0
    assert actions["6788"].reference_price == D("215.00")


def test_tpex_reductions_parse_ratio_and_refund_from_detail() -> None:
    _, tpex = _providers()
    raw = tpex.fetch_corporate_actions("tpex", "capital_reduction", *YEAR_2025)
    actions = _by_symbol(tpex.parse_corporate_actions(raw))
    assert actions["2740"].ex_date == date(2025, 1, 13)
    assert actions["2740"].ratio == D("0.55")
    assert actions["2740"].cash_dividend is None  # no refund
    refund = actions["3290"]
    assert refund.cash_dividend is not None
    assert refund.cash_dividend > 0


def test_providers_refuse_tables_they_do_not_publish() -> None:
    _, tpex = _providers()
    assert ("tpex", "par_value_change") not in tpex.action_sources
    with pytest.raises(Exception, match="does not publish"):
        tpex.fetch_corporate_actions("tpex", "par_value_change", *YEAR_2025)


# ----------------------------------------------------------------------------- checks


def _action(**overrides: Any) -> CorporateAction:
    values: dict[str, Any] = {
        "symbol": "2330",
        "market": "twse",
        "ex_date": date(2025, 6, 12),
        "action_type": "cash_dividend",
        "prev_close": D(1000),
        "reference_price": D(995),
    }
    return CorporateAction(**(values | overrides))


def test_quality_checks() -> None:
    assert check_corporate_action(_action()) == []
    assert check_corporate_action(_action(reference_price=D(1010))) == ["dividend_raises_price"]
    assert check_corporate_action(_action(reference_price=D(1))) == ["factor_out_of_range"]
    junk = _action(prev_close=D(0), reference_price=D("-2.30"))  # seen on TPEx (3454, 2011)
    assert check_corporate_action(junk) == ["non_positive_price"]
    no_prices = _action(prev_close=None, reference_price=None)
    assert check_corporate_action(no_prices) == ["no_reference_price"]
    ratio_only = _action(action_type="split", prev_close=None, reference_price=None, ratio=D(4))
    assert check_corporate_action(ratio_only) == []


def test_year_chunks() -> None:
    assert year_chunks(date(2024, 11, 1), date(2025, 2, 1)) == [
        (date(2024, 11, 1), date(2024, 12, 31)),
        (date(2025, 1, 1), date(2025, 2, 1)),
    ]
    assert year_chunks(date(2025, 2, 2), date(2025, 2, 1)) == []


# ----------------------------------------------------------------------------- jobs


@pytest.fixture
def run(clean_db: Engine, tmp_path: Path) -> Any:
    store = LocalRawStore(clean_db, tmp_path)
    router = official_router(store)

    def _run(name: str, **params: Any) -> JobRunResult:
        return run_job(
            name, params, engine=clean_db, rawstore=store, notifier=ConsoleNotifier(), router=router
        )

    return _run


@pytest.fixture
def stocks(clean_db: Engine) -> dict[str, int]:
    with clean_db.begin() as conn:
        rows = conn.execute(
            text(
                "INSERT INTO stocks (symbol, market, type, name, listed_date) VALUES "
                "('1598', 'twse', 'stock', '岱宇', '2000-01-01'), "
                "('0050', 'twse', 'etf', '元大台灣50', '2003-06-30'), "
                "('2740', 'tpex', 'stock', '天蔥', '2010-01-01'), "
                "('6762', 'tpex', 'stock', '達亞', '2020-01-01') RETURNING symbol, id"
            )
        ).all()
    return {r.symbol: r.id for r in rows}


def _rows(engine: Engine, sql: str, **params: Any) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql), params).all())


def test_sync_corporate_actions_imports_known_symbols(
    run: Any, clean_db: Engine, stocks: dict[str, int]
) -> None:
    result = run("sync_corporate_actions", start="2025-01-01", end="2025-12-31")
    assert result.status == "succeeded"
    assert result.message.endswith("沒有官方來源：tpex:etf_split、tpex:par_value_change")
    rows = {
        (r.stock_id, r.action_type): r
        for r in _rows(
            clean_db,
            "SELECT stock_id, action_type, ex_date, price_factor, cash_dividend, source "
            "FROM corporate_actions",
        )
    }
    assert set(rows) == {
        (stocks["1598"], "cash_dividend"),
        (stocks["0050"], "split"),
        (stocks["2740"], "capital_reduction"),
        (stocks["6762"], "cash_and_stock_dividend"),
    }
    split = rows[(stocks["0050"], "split")]
    assert split.price_factor == (D("47.16") / D("188.65")).quantize(D("1E-10"))
    assert rows[(stocks["1598"], "cash_dividend")].source == "twse"
    # Rerun with the same tables writes nothing (rule 4).
    again = run("sync_corporate_actions", start="2025-01-01", end="2025-12-31")
    assert again.rows_written == 0


def _bars(engine: Engine, stock_id: int, closes: dict[str, str]) -> None:
    with engine.begin() as conn:
        for day, close in closes.items():
            conn.execute(
                text(
                    "INSERT INTO prices_daily "
                    "(stock_id, trade_date, open, high, low, close, volume, source) "
                    "VALUES (:id, :d, :c, :c, :c, :c, 1000, 'test')"
                ),
                {"id": stock_id, "d": day, "c": close},
            )


def test_compute_adj_factors_and_gap_flags(
    run: Any, clean_db: Engine, stocks: dict[str, int]
) -> None:
    etf = stocks["0050"]
    # Around the 1 -> 4 split on 2025-06-18, plus a 2740 gap no event explains.
    _bars(clean_db, etf, {"2025-06-10": "188.65", "2025-06-18": "47.20", "2025-06-19": "47.50"})
    _bars(clean_db, stocks["6762"], {"2025-01-02": "100", "2025-01-03": "40"})
    run("sync_corporate_actions", start="2025-01-01", end="2025-12-31")

    result = run("compute_adj_factors")
    assert result.status == "succeeded"
    factors = dict(
        (r.trade_date, r.adj_factor)
        for r in _rows(
            clean_db,
            "SELECT trade_date, adj_factor FROM prices_daily WHERE stock_id = :id",
            id=etf,
        )
    )
    split = (D("47.16") / D("188.65")).quantize(D("1E-10"))
    assert factors == {
        date(2025, 6, 10): split,
        date(2025, 6, 18): D(1),
        date(2025, 6, 19): D(1),
    }
    gaps = _rows(
        clean_db,
        "SELECT symbol, ex_date, reasons, resolved_at FROM corporate_actions_quarantine",
    )
    assert [(g.symbol, g.ex_date, g.reasons, g.resolved_at) for g in gaps] == [
        ("6762", date(2025, 1, 3), ["unexplained_price_gap"], None)
    ]
    assert run("compute_adj_factors").rows_written == 0  # idempotent

    # Once an event explains the gap, the flag resolves itself.
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO corporate_actions "
                "(stock_id, ex_date, action_type, prev_close, reference_price, source) "
                "VALUES (:id, '2025-01-03', 'split', 100, 40, 'manual')"
            ),
            {"id": stocks["6762"]},
        )
    run("compute_adj_factors")
    assert _rows(clean_db, "SELECT resolution FROM corporate_actions_quarantine") == [
        ("explained",)
    ]


def test_tpex_rights_offering_is_not_a_stock_dividend() -> None:
    # 6846 on 2025: 除權 with only a cash capital increase at 65 (reference rose 63.30 -> 63.40).
    cells = {
        "除權息日期": "114/04/10",
        "代號": "6846",
        "除權息前收盤價": "63.30",
        "除權息參考價": "63.40",
        "權/息": "除權",
        "現金股利": "0.00000000",
        "每仟股無償配股": "0.00000000",
        "現金增資認購價": "65.00",
    }
    action = tpex_dividend_row(cells)
    assert action is not None
    assert action.action_type == "rights_issue"
    assert check_corporate_action(action) == []


def test_accepted_event_supersedes_its_quarantined_version(
    clean_db: Engine, stocks: dict[str, int]
) -> None:
    bad = _action(symbol="1598", reference_price=D(1010))
    with clean_db.begin() as conn:
        assert store_corporate_actions(conn, [bad], "twse", None).quarantined == 1
        assert store_corporate_actions(conn, [_action(symbol="1598")], "twse", None).written == 1
    assert _rows(clean_db, "SELECT resolution FROM corporate_actions_quarantine") == [
        ("superseded",)
    ]


def test_gap_flags_carry_a_share_ratio_guess(
    run: Any, clean_db: Engine, stocks: dict[str, int]
) -> None:
    _bars(clean_db, stocks["6762"], {"2025-01-02": "100", "2025-01-03": "25.5"})
    run("compute_adj_factors")
    [(payload,)] = _rows(clean_db, "SELECT payload FROM corporate_actions_quarantine")
    assert payload["ratio"] == "0.2550"
    assert payload["suggestion"] == {
        "ratio": "4",
        "action_type": "split",
        "implied_move": "0.0200",
    }


def test_imported_event_replaces_a_manual_one(clean_db: Engine, stocks: dict[str, int]) -> None:
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO corporate_actions (stock_id, ex_date, action_type, ratio, source) "
                "VALUES (:id, '2025-06-12', 'split', 2, 'manual')"
            ),
            {"id": stocks["1598"]},
        )
        assert store_corporate_actions(conn, [_action(symbol="1598")], "twse", None).written == 1
    assert _rows(clean_db, "SELECT action_type, source FROM corporate_actions") == [
        ("cash_dividend", "twse")
    ]


# ----------------------------------------------------------------------------- details


def _detail(**overrides: Any) -> DividendDetail:
    values: dict[str, Any] = {
        "symbol": "1605",
        "ex_date": date(2025, 6, 4),
        "cash_dividend": D(0),
        "stock_dividend_ratio": D(0),
        "rights_ratio": D(0),
    }
    return DividendDetail(**(values | overrides))


def test_twse_dividend_detail_parser() -> None:
    twse, _ = _providers()
    # 1605 華新 權息 2025-06-04: cash 0.5 plus a cash capital increase at 20. Holders
    # subscribe 79.378 per 1000, which is 320M of the 400M offering: the reference price
    # counts the whole offering, 0.0992 per share.
    raw = twse.fetch_dividend_detail("twse", "1605", date(2025, 6, 4))
    assert twse.parse_dividend_detail(raw) == [
        _detail(
            cash_dividend=D("0.5"),
            rights_ratio=D("0.09922276"),
            subscription_price=D(20),
        )
    ]
    # 6423 權 2025-06-12: 20.3 free shares per 1000, no cash.
    raw = twse.fetch_dividend_detail("twse", "6423", date(2025, 6, 12))
    [detail] = twse.parse_dividend_detail(raw)
    assert (detail.cash_dividend, detail.stock_dividend_ratio, detail.subscription_price) == (
        D(0),
        D("0.0203"),
        None,
    )
    # Before 2009 the page has nothing.
    raw = twse.fetch_dividend_detail("twse", "2330", date(2008, 7, 16))
    assert twse.parse_dividend_detail(raw) == []


def test_sync_dividend_details_fills_parts_once(
    run: Any, clean_db: Engine, stocks: dict[str, int]
) -> None:
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO stocks (symbol, market, type, name, listed_date) VALUES "
                "('1605', 'twse', 'stock', '華新', '1962-02-09'), "
                "('6423', 'twse', 'stock', '億而得-創', '2020-01-01')"
            )
        )
    run("sync_corporate_actions", start="2025-01-01", end="2025-12-31")
    result = run("sync_dividend_details", start="2025-01-01", end="2025-12-31")
    assert result.status == "succeeded"
    assert result.rows_written == 2
    rows = {
        r.symbol: r
        for r in _rows(
            clean_db,
            "SELECT s.symbol, c.action_type, c.cash_dividend, c.stock_dividend_ratio, "
            "c.rights_ratio, c.subscription_price, c.detail_raw_object_id FROM corporate_actions c "
            "JOIN stocks s ON s.id = c.stock_id WHERE s.symbol IN ('1605', '6423')",
        )
    }
    # 權息 that was cash plus a subscription: the label stays, the parts tell.
    華新 = rows["1605"]
    assert (華新.action_type, 華新.cash_dividend, 華新.stock_dividend_ratio) == (
        "cash_and_stock_dividend",
        D("0.5"),
        D(0),
    )
    assert (華新.rights_ratio, 華新.subscription_price) == (D("0.09922276"), D(20))
    assert (rows["6423"].action_type, rows["6423"].stock_dividend_ratio) == (
        "stock_dividend",
        D("0.0203"),
    )
    assert all(r.detail_raw_object_id is not None for r in rows.values())
    # Done rows are not fetched again (rule 4); re-importing the table (which has no
    # parts) neither duplicates the event nor erases them.
    assert run("sync_dividend_details", start="2025-01-01", end="2025-12-31").rows_written == 0
    run("sync_corporate_actions", start="2025-01-01", end="2025-12-31")
    assert _rows(
        clean_db,
        "SELECT cash_dividend FROM corporate_actions WHERE stock_id = "
        "(SELECT id FROM stocks WHERE symbol = '1605')",
    ) == [(D("0.5"),)]


def test_detail_parts_must_reproduce_the_reference_price() -> None:
    # 1605: (20.90 - 0.5 + 20 * 0.09922276) / 1.09922276 = 20.364 vs published 20.36.
    good = _detail(cash_dividend=D("0.5"), rights_ratio=D("0.09922276"), subscription_price=D(20))
    assert check_dividend_detail(good, D("20.90"), D("20.36")) == []
    wrong = _detail(cash_dividend=D("0.5"), stock_dividend_ratio=D("0.1"))
    assert check_dividend_detail(wrong, D("20.90"), D("20.36")) == ["parts_do_not_match_reference"]
    no_price = _detail(rights_ratio=D("0.1"))
    assert check_dividend_detail(no_price, D("20.90"), D("20.36")) == ["rights_without_price"]
    assert check_dividend_detail(wrong, None, None) == []  # nothing to compare with


def test_sync_dividend_details_quarantines_and_reparses(
    run: Any, clean_db: Engine, stocks: dict[str, int]
) -> None:
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO stocks (symbol, market, type, name, listed_date) VALUES "
                "('1605', 'twse', 'stock', '華新', '1962-02-09'), "
                "('6423', 'twse', 'stock', '億而得-創', '2020-01-01')"
            )
        )
    run("sync_corporate_actions", start="2025-01-01", end="2025-12-31")
    # Pretend the exchange had published another reference price for 6423.
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "UPDATE corporate_actions SET reference_price = 80 WHERE stock_id = "
                "(SELECT id FROM stocks WHERE symbol = '6423')"
            )
        )
    result = run("sync_dividend_details", start="2025-01-01", end="2025-12-31")
    assert "與參考價不符隔離 1" in result.message
    assert _rows(
        clean_db,
        "SELECT symbol, reasons, resolution FROM corporate_actions_quarantine "
        "WHERE source = 'twse:detail'",
    ) == [("6423", ["parts_do_not_match_reference"], None)]
    assert _rows(
        clean_db,
        "SELECT stock_dividend_ratio FROM corporate_actions WHERE stock_id = "
        "(SELECT id FROM stocks WHERE symbol = '6423')",
    ) == [(None,)]
    # Once fixed, re-parsing the stored page (no network) stores the parts.
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "UPDATE corporate_actions SET reference_price = 88.01 WHERE stock_id = "
                "(SELECT id FROM stocks WHERE symbol = '6423')"
            )
        )
    again = run("sync_dividend_details", start="2025-01-01", end="2025-12-31", reparse="true")
    assert again.message.startswith("2025-01-01～2025-12-31：重新解析 2、補上 2")
    assert _rows(
        clean_db,
        "SELECT resolution FROM corporate_actions_quarantine WHERE source = 'twse:detail'",
    ) == [("superseded",)]
