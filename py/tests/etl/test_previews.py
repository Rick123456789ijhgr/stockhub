"""除權除息預告表: parsers of both exchanges and the snapshot import (no network)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine, text

from stockhub.common.notifier import ConsoleNotifier
from stockhub.common.rawstore import LocalRawStore
from stockhub.etl.jobs.base import JobRunResult, run_job
from stockhub.etl.jobs.previews import store_previews
from stockhub.etl.providers.base import ExRightsPreview, preview_action_type
from stockhub.etl.providers.http import make_client, preview_fields
from stockhub.etl.providers.tpex import TpexProvider
from stockhub.etl.providers.twse import TwseProvider

from .official_sources import official_handler, official_router

D = Decimal


def _by_symbol(items: list[ExRightsPreview]) -> dict[str, ExRightsPreview]:
    return {v.symbol: v for v in items}


def test_twse_previews() -> None:
    twse = TwseProvider(make_client(httpx.MockTransport(official_handler)))
    got = _by_symbol(twse.parse_ex_rights_previews(twse.fetch_ex_rights_previews("twse")))
    assert set(got) == {"00406A", "0056", "00714", "1711", "2025", "9999"}
    etf = got["00714"]
    assert (etf.ex_date, etf.label, etf.action_type, etf.cash_dividend) == (
        date(2026, 10, 19),
        "息",
        "cash_dividend",
        D("0.123000"),
    )
    # ETF amount not announced yet
    assert got["0056"].cash_dividend is None
    assert got["0056"].action_type == "cash_dividend"
    rights = got["1711"]
    assert (rights.action_type, rights.rights_ratio, rights.subscription_price) == (
        "rights_issue",
        D("0.09128214"),
        D("34.0000"),
    )
    assert got["2025"].subscription_price is None  # 尚未公告


def test_tpex_previews() -> None:
    tpex = TpexProvider(make_client(httpx.MockTransport(official_handler)))
    got = _by_symbol(tpex.parse_ex_rights_previews(tpex.fetch_ex_rights_previews("tpex")))
    assert got["1565"].label == "息"
    assert got["1565"].cash_dividend == D("5.80000000")
    both = got["2063"]
    assert (both.label, both.action_type, both.stock_dividend_ratio) == (
        "權息",
        "cash_and_stock_dividend",
        D("0.09999999"),
    )
    assert got["3691"].action_type == "rights_issue"
    assert got["3691"].subscription_price is None  # 註4


def test_classification_and_unannounced_cash() -> None:
    assert preview_action_type("權", None, D(0), D(0)) == "rights_issue"
    assert preview_action_type("權", D(0), D("0.05"), D(0)) == "stock_dividend"
    assert preview_action_type("息", None, D(0), D(0)) == "cash_dividend"
    assert preview_fields("除息", "0.00000000", "0", "0", "0.00")["cash_dividend"] is None
    with pytest.raises(ValueError, match="label"):
        preview_fields("X", "", "", "", "")


@pytest.fixture
def stocks(clean_db: Engine) -> dict[str, int]:
    with clean_db.begin() as conn:
        rows = conn.execute(
            text(
                "INSERT INTO stocks (symbol, market, type, name, listed_date) VALUES "
                "('00714', 'twse', 'etf', '群益道瓊美國地產', '2017-01-01'), "
                "('0056', 'twse', 'etf', '元大高股息', '2007-12-26'), "
                "('1711', 'twse', 'stock', '永光', '1990-01-01'), "
                "('2063', 'tpex', 'stock', '世鎧', '2010-01-01') RETURNING symbol, id"
            )
        ).all()
    return {r.symbol: r.id for r in rows}


def test_sync_job_imports_known_symbols_once(
    clean_db: Engine, tmp_path: Path, stocks: dict[str, int]
) -> None:
    store = LocalRawStore(clean_db, tmp_path)
    router = official_router(store)

    def run() -> JobRunResult:
        return run_job(
            "sync_ex_rights_previews",
            {},
            engine=clean_db,
            rawstore=store,
            notifier=ConsoleNotifier(),
            router=router,
        )

    first = run()
    assert first.status == "succeeded", first.error
    with clean_db.connect() as conn:
        rows = conn.execute(
            text("SELECT stock_id, source, cash_dividend FROM corporate_action_previews")
        ).all()
    assert {(r.stock_id, r.source) for r in rows} == {
        (stocks["00714"], "twse"),
        (stocks["0056"], "twse"),
        (stocks["1711"], "twse"),
        (stocks["2063"], "tpex"),
    }
    assert run().rows_written == 0  # same snapshot (rule 4)


def test_store_drops_future_events_missing_from_the_snapshot(
    clean_db: Engine, stocks: dict[str, int]
) -> None:
    def preview(symbol: str, ex_date: date, cash: str | None) -> ExRightsPreview:
        return ExRightsPreview(
            symbol=symbol,
            market="twse",
            ex_date=ex_date,
            label="息",
            action_type="cash_dividend",
            cash_dividend=None if cash is None else D(cash),
        )

    today = date(2026, 10, 19)
    past, soon, later = date(2026, 10, 1), date(2026, 10, 22), date(2026, 11, 20)
    with clean_db.begin() as conn:
        first = store_previews(
            conn,
            [preview("0056", past, "1"), preview("0056", soon, None), preview("1711", later, "2")],
            "twse",
            None,
            today,
        )
        assert first.written == 3
        # Next snapshot: the amount of `soon` is announced, `later` was cancelled, the past
        # event is no longer listed (kept: it is history).
        second = store_previews(conn, [preview("0056", soon, "0.866")], "twse", None, today)
        assert (second.written, second.removed) == (1, 1)
        left = conn.execute(
            text("SELECT ex_date, cash_dividend FROM corporate_action_previews ORDER BY ex_date")
        ).all()
    assert [(r.ex_date, r.cash_dividend) for r in left] == [(past, D(1)), (soon, D("0.866"))]
