"""Intraday quotes: MIS parser, latest-snapshot upsert, polling loop (no network)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, text

from stockhub.common.notifier import ConsoleNotifier
from stockhub.common.rawstore import LocalRawStore
from stockhub.common.timeutil import TAIPEI
from stockhub.etl.jobs.base import JobRunResult, run_job
from stockhub.etl.jobs.quotes import PollQuotesJob, store_quotes
from stockhub.etl.providers.base import RawResponse
from stockhub.etl.providers.http import make_client
from stockhub.etl.providers.mis import TwseMisProvider

from .official_sources import fixture, official_handler, official_router

D = Decimal


def _mis() -> TwseMisProvider:
    return TwseMisProvider(make_client(httpx.MockTransport(official_handler)))


def test_mis_snapshot_parsing() -> None:
    mis = _mis()
    raw = mis.fetch_quotes([("2330", "twse"), ("6488", "tpex")])
    quotes = {q.symbol: q for q in mis.parse_quotes(raw)}
    tsmc = quotes["2330"]
    assert (tsmc.market, tsmc.trade_date) == ("twse", date(2026, 10, 16))
    assert tsmc.at == datetime(2026, 10, 16, 5, 30, tzinfo=UTC)  # 13:30 Taipei
    assert (tsmc.price, tsmc.open, tsmc.prev_close) == (D("2420"), D("2430"), D("2440"))
    assert (tsmc.bid, tsmc.ask) == (D("2420"), D("2425"))
    assert tsmc.volume == 33_257_000  # lots -> shares
    assert quotes["6488"].market == "tpex"


def test_mis_tick_without_trade_has_no_price() -> None:
    data = json.loads(fixture("twse_mis_20261016.json"))
    data["msgArray"][0]["z"] = "-"
    data["msgArray"][0]["b"] = "-"
    quotes = _mis().parse_quotes(RawResponse("stock_info", data))
    assert (quotes[0].price, quotes[0].bid) == (None, None)


def test_mis_error_code_is_a_parse_error() -> None:
    with pytest.raises(ValueError, match="rtcode"):
        _mis().parse_quotes(RawResponse("stock_info", {"rtcode": "9999", "rtmessage": "x"}))


def test_mis_refuses_oversized_batches() -> None:
    with pytest.raises(ValueError, match="at most"):
        _mis().fetch_quotes([(str(i), "twse") for i in range(51)])


# ----------------------------------------------------------------------------- storage


@pytest.fixture
def tsmc(clean_db: Engine) -> Iterator[int]:
    with clean_db.begin() as conn:
        stock_id: int = conn.execute(
            text(
                "INSERT INTO stocks (symbol, market, type, name, listed_date) "
                "VALUES ('2330', 'twse', 'stock', '台積電', '1994-09-05') RETURNING id"
            )
        ).scalar_one()
    yield stock_id
    with clean_db.begin() as conn:  # schema tests insert 2330 themselves
        conn.execute(text("TRUNCATE stocks RESTART IDENTITY CASCADE"))


def _latest(engine: Engine) -> Any:
    with engine.connect() as conn:
        return conn.execute(text("SELECT price, volume, quote_time FROM quotes_latest")).one()


def test_store_quotes_keeps_last_price_and_never_goes_back(clean_db: Engine, tsmc: int) -> None:
    quotes = {q.symbol: q for q in _mis().parse_quotes(_mis().fetch_quotes([("2330", "twse")]))}
    first = quotes["2330"]
    no_trade = first.model_copy(
        update={"price": None, "volume": first.volume + 1000, "at": first.at + timedelta(seconds=5)}
    )
    older = first.model_copy(update={"price": D(1), "at": first.at - timedelta(minutes=1)})
    with clean_db.begin() as conn:
        assert store_quotes(conn, [first], {"2330": tsmc}, "twse_mis", None) == 1
        assert store_quotes(conn, [first], {"2330": tsmc}, "twse_mis", None) == 0  # unchanged
        assert store_quotes(conn, [no_trade], {"2330": tsmc}, "twse_mis", None) == 1
        assert store_quotes(conn, [older], {"2330": tsmc}, "twse_mis", None) == 0
    price, volume, _ = _latest(clean_db)
    assert (price, volume) == (D("2420.0000"), first.volume + 1000)


def test_store_quotes_keeps_same_day_reference_when_a_snapshot_lacks_it(
    clean_db: Engine, tsmc: int
) -> None:
    first = _mis().parse_quotes(_mis().fetch_quotes([("2330", "twse")]))[0]
    partial = first.model_copy(
        update={"open": None, "prev_close": None, "at": first.at + timedelta(seconds=5)}
    )
    next_day = partial.model_copy(
        update={
            "trade_date": first.trade_date + timedelta(days=3),
            "at": first.at + timedelta(days=3),
        }
    )
    query = text("SELECT open, prev_close FROM quotes_latest")
    with clean_db.begin() as conn:
        store_quotes(conn, [first], {"2330": tsmc}, "twse_mis", None)
        store_quotes(conn, [partial], {"2330": tsmc}, "fake_stream", None)
        assert tuple(conn.execute(query).one()) == (D("2430.0000"), D("2440.0000"))
        store_quotes(conn, [next_day], {"2330": tsmc}, "fake_stream", None)
        assert tuple(conn.execute(query).one()) == (None, None)  # not carried across days


# ----------------------------------------------------------------------------- job


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)


def _taipei(hour: int, minute: int) -> datetime:
    return datetime(2026, 10, 16, hour, minute, tzinfo=TAIPEI)


def _run(engine: Engine, tmp_path: Path, clock: FakeClock, **params: Any) -> JobRunResult:
    store = LocalRawStore(engine, tmp_path)
    return run_job(
        "poll_quotes",
        params,
        engine=engine,
        rawstore=store,
        notifier=ConsoleNotifier(),
        router=official_router(store),
        job_factory=lambda cls: PollQuotesJob(now=lambda: clock.now, sleep=clock.sleep),
    )


def test_poll_without_targets_is_skipped(clean_db: Engine, tmp_path: Path) -> None:
    result = _run(clean_db, tmp_path, FakeClock(_taipei(10, 0)))
    assert result.status == "skipped"


def test_poll_waits_for_the_open_then_polls_until_the_close(
    clean_db: Engine, tmp_path: Path, tsmc: int
) -> None:
    with clean_db.begin() as conn:
        conn.execute(text("INSERT INTO watchlist (stock_id) VALUES (:id)"), {"id": tsmc})
    clock = FakeClock(_taipei(8, 59))
    result = _run(clean_db, tmp_path, clock, interval=60, until="09:02")
    assert result.status == "succeeded"
    # 08:59 waits 60 s for the open, then 09:00, 09:01, 09:02 (>= until) are polled.
    assert result.message == "1 檔，輪詢 3 次"
    assert clock.sleeps == [60.0, 60.0, 60.0]
    assert _latest(clean_db)[0] == D("2420.0000")


def test_poll_once_with_explicit_symbols(clean_db: Engine, tmp_path: Path, tsmc: int) -> None:
    clock = FakeClock(_taipei(20, 0))
    result = _run(clean_db, tmp_path, clock, symbols="2330", once="true")
    assert (result.status, result.message, result.rows_written) == (
        "succeeded",
        "1 檔，輪詢 1 次",
        1,
    )
    assert clock.sleeps == []
