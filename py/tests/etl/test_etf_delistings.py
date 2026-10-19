"""Delisted ETFs derived from stored daily tables (no network)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text

from stockhub.common.notifier import ConsoleNotifier
from stockhub.common.rawstore import LocalRawStore
from stockhub.etl.jobs.base import JobRunResult, run_job
from stockhub.etl.jobs.etf_delistings import (
    DERIVED_REASON,
    Sighting,
    derive_delistings,
    is_etf_symbol,
)
from stockhub.etl.providers.base import Delisting, Market

from .official_sources import fixture, official_router


def test_is_etf_symbol() -> None:
    assert all(is_etf_symbol(s) for s in ["0050", "00631L", "00679B", "006201"])
    assert all(is_etf_symbol(s) for s in ["0080", "0099"])
    # 0001～0049 were closed-end funds; 020011 is an ETN.
    assert not any(is_etf_symbol(s) for s in ["0001", "0015", "0049", "020011", "2330", "9105"])


def test_derive_delistings_keeps_codes_still_trading() -> None:
    sightings = {
        "00999": Sighting("twse", "舊ETF", date(2020, 1, 2), date(2026, 5, 6)),
        "00888": Sighting("tpex", "新ETF", date(2026, 10, 1), date(2026, 10, 16)),
    }
    latest: dict[Market, date] = {"twse": date(2026, 10, 16), "tpex": date(2026, 10, 16)}
    delisted, trading = derive_delistings(sightings, latest, {date(2026, 5, 6): date(2026, 5, 7)})
    assert delisted == [
        Delisting(
            symbol="00999",
            name="舊ETF",
            market="twse",
            delisted_date=date(2026, 5, 7),
            reason=DERIVED_REASON,
        )
    ]
    assert trading == ["00888"]


@pytest.fixture
def run(clean_db: Engine, tmp_path: Path) -> Any:
    store = LocalRawStore(clean_db, tmp_path)
    router = official_router(store)

    def _run(name: str, **params: Any) -> JobRunResult:
        return run_job(
            name, params, engine=clean_db, rawstore=store, notifier=ConsoleNotifier(), router=router
        )

    _run.store = store  # type: ignore[attr-defined]
    return _run


def test_derive_delisted_etfs_from_stored_tables(run: Any, clean_db: Engine) -> None:
    run("sync_stocks")
    run("daily_prices", date="2026-10-16")
    # The day before, the TWSE table also listed an ETF that is gone on 10-16.
    table = json.loads(fixture("twse_mi_index_20261016.json"))
    table["date"] = "20261015"
    for t in table["tables"]:
        for row in t.get("data") or []:
            if row[0] == "2330":
                row[0], row[1] = "00999", "測試ETF"
    earlier = json.dumps(table, ensure_ascii=False).encode()
    run.store.put("twse", "mi_index", earlier, params={"date": "2026-10-15", "market": "twse"})

    result = run("derive_delisted_etfs")
    assert result.status == "succeeded", result.message
    with clean_db.connect() as conn:
        stock = conn.execute(
            text(
                "SELECT id, market, type, name, listed_date, delisted_date, delisting_reason "
                "FROM stocks WHERE symbol = '00999'"
            )
        ).one()
        bars = conn.execute(
            text("SELECT trade_date, close FROM prices_daily WHERE stock_id = :id"),
            {"id": stock.id},
        ).all()
    assert stock[1:] == (
        "twse",
        "etf",
        "測試ETF",
        date(2026, 10, 15),
        date(2026, 10, 16),
        DERIVED_REASON,
    )
    assert [(b.trade_date, b.close) for b in bars] == [(date(2026, 10, 15), Decimal("2420.0000"))]
    # ETNs (020011) are not ETFs; a rerun changes nothing (rule 4).
    assert run("derive_delisted_etfs").rows_written == 0
