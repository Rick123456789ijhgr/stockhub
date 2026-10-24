"""Streaming quotes: cache merging, reconnect, fallback, cooldown, staleness (no network)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, text

from stockhub.common.notifier import Notifier, Severity
from stockhub.common.rawstore import LocalRawStore
from stockhub.common.settings import load_settings
from stockhub.common.timeutil import TAIPEI
from stockhub.etl.jobs.base import JobRunResult, run_job
from stockhub.etl.jobs.quotes import PollQuotesJob
from stockhub.etl.providers.base import Market, Quote, QuoteStreamProvider, QuoteUpdate
from stockhub.etl.providers.fake import FakeQuoteStreamProvider
from stockhub.etl.providers.http import make_client
from stockhub.etl.providers.mis import TwseMisProvider
from stockhub.etl.providers.registry import ProviderRegistry, registered_providers
from stockhub.etl.providers.router import ProviderRouter, RateLimiter, RetryPolicy
from stockhub.etl.quote_stream import LatestQuotes, QuoteStreamSession, StreamPolicy

from .official_sources import official_handler

D = Decimal
SYMBOLS: list[tuple[str, Market]] = [
    ("2330", "twse"),
    ("0050", "twse"),
    ("2317", "twse"),
    ("6488", "tpex"),
]
POLICY = StreamPolicy(reconnect_attempts=3, fallback_cooldown=300, stale_after=120)


def _at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 10, 16, hour, minute, second, tzinfo=TAIPEI)


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start
        self.sleeps: list[float] = []
        self.on_sleep: Callable[[], None] = lambda: None

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)
        self.on_sleep()

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _session(*streams: QuoteStreamProvider, clock: Clock) -> QuoteStreamSession:
    session = QuoteStreamSession(streams, POLICY, lambda: clock.now, clock.sleep)
    session.set_symbols(SYMBOLS)
    return session


# ----------------------------------------------------------------------------- contract


def test_stream_providers_implement_the_interface() -> None:
    streams = [c for c in registered_providers().values() if issubclass(c, QuoteStreamProvider)]
    assert streams, "at least the fake stream is registered"
    for cls in streams:
        provider = cls()
        assert provider.max_subscriptions > 0
        assert not provider.is_connected()


def test_router_lists_configured_streams_only() -> None:
    def router(**env: Any) -> ProviderRouter:
        settings = load_settings(database_url="postgresql://x", **env)
        return ProviderRouter(ProviderRegistry.from_settings(settings), None)  # type: ignore[arg-type]

    assert router().quote_streams() == []
    streams = router(providers_quote_stream="fake_stream").quote_streams()
    assert [s.name for s in streams] == ["fake_stream"]


def test_fake_messages_keep_symbol_and_market() -> None:
    fake = FakeQuoteStreamProvider()
    received: list[Any] = []
    fake.connect(received.append, lambda _: None)
    fake.subscribe(SYMBOLS)
    for symbol, _ in SYMBOLS:
        fake.push(symbol, _at(10, 0), price=D("10.5"), volume=1000)
    updates = [u for m in received for u in fake.parse_message(m)]
    assert [(u.symbol, u.market) for u in updates] == SYMBOLS
    assert updates[0].at == _at(10, 0)
    assert updates[0].price == D("10.5")


# ----------------------------------------------------------------------------- cache


def _tick(at: datetime, **fields: Any) -> QuoteUpdate:
    return QuoteUpdate(symbol="2330", market="twse", kind="tick", at=at, **fields)


def _bidask(at: datetime, bid: Decimal | None, ask: Decimal | None) -> QuoteUpdate:
    return QuoteUpdate(symbol="2330", market="twse", kind="bidask", at=at, bid=bid, ask=ask)


def test_bidask_does_not_erase_the_last_trade() -> None:
    cache = LatestQuotes()
    cache.apply(_tick(_at(10, 0), price=D(100), volume=5000, prev_close=D(99)), "s")
    cache.apply(_bidask(_at(10, 0, 1), D("99.5"), D(100)), "s")
    cache.apply(_bidask(_at(10, 0, 2), None, D(100)), "s")  # nothing bid: limit down
    quote = cache.get("2330")
    assert quote is not None
    assert (quote.price, quote.volume, quote.prev_close) == (D(100), 5000, D(99))
    assert (quote.bid, quote.ask, quote.at) == (None, D(100), _at(10, 0, 2))
    assert quote.trade_date == date(2026, 10, 16)


def test_older_update_only_fills_missing_fields() -> None:
    cache = LatestQuotes()
    cache.apply(_tick(_at(10, 0), price=D(100), volume=5000), "s")
    cache.apply(_tick(_at(9, 59), price=D(98), volume=4000, prev_close=D(99)), "s")
    quote = cache.get("2330")
    assert quote is not None
    assert (quote.price, quote.volume, quote.prev_close, quote.at) == (
        D(100),
        5000,
        D(99),
        _at(10, 0),
    )


def test_new_trading_day_starts_afresh() -> None:
    cache = LatestQuotes()
    cache.apply(_tick(_at(13, 30), price=D(100), volume=5000, prev_close=D(99)), "s")
    cache.apply(_tick(_at(13, 30) + timedelta(days=1), price=D(101), volume=10), "s")
    quote = cache.get("2330")
    assert quote is not None
    assert (quote.price, quote.volume, quote.prev_close) == (D(101), 10, None)


def test_polled_snapshot_keeps_same_day_fields_and_dirty_groups_by_source() -> None:
    cache = LatestQuotes()
    cache.apply(_tick(_at(10, 0), price=D(100), volume=5000, prev_close=D(99), open=D(98)), "s")
    polled = Quote(
        symbol="2330", market="twse", trade_date=date(2026, 10, 16), at=_at(10, 1),
        price=D(101), volume=6000,
    )  # fmt: skip
    cache.put(polled, "poll", dirty=False)
    cache.put(polled.model_copy(update={"at": _at(9, 0), "price": D(1)}), "poll")  # older
    assert cache.take_dirty() == {}  # the caller already stored the polled snapshot
    quote = cache.get("2330")
    assert quote is not None
    assert (quote.price, quote.prev_close, quote.open) == (D(101), D(99), D(98))


# ----------------------------------------------------------------------------- session


def test_reconnect_resubscribes_every_symbol() -> None:
    clock = Clock(_at(10, 0))
    fake = FakeQuoteStreamProvider()
    session = _session(fake, clock=clock)
    assert session.start() == "streaming"
    assert fake.subscribed == dict(SYMBOLS)

    fake.drop("network")
    assert fake.subscribed == {}
    assert session.ensure() == "streaming"
    assert fake.connects == 2
    assert session.reconnects == 1
    assert fake.subscribed == dict(SYMBOLS)
    assert session.streamed == {s for s, _ in SYMBOLS}


def test_reconnect_backs_off_then_falls_back_to_polling() -> None:
    clock = Clock(_at(10, 0))
    fake = FakeQuoteStreamProvider(fail_connects=99)
    session = _session(fake, clock=clock)
    assert session.start() == "polling"
    assert fake.connects == 3
    assert clock.sleeps == [1.0, 2.0]  # no sleep after the last attempt
    assert (session.fallbacks, session.streamed) == (1, frozenset())


def test_backoff_is_capped() -> None:
    policy = StreamPolicy(max_delay=30)
    assert [policy.delay(n) for n in range(1, 8)] == [1, 2, 4, 8, 16, 30, 30]


def test_rejected_credentials_are_not_retried() -> None:
    clock = Clock(_at(10, 0))
    fake = FakeQuoteStreamProvider(fail_connects=1, permanent=True)
    session = _session(fake, clock=clock)
    assert session.start() == "polling"
    assert (fake.connects, clock.sleeps) == (1, [])


def test_exhausted_primary_falls_back_to_the_secondary_stream() -> None:
    clock = Clock(_at(10, 0))
    primary = FakeQuoteStreamProvider(fail_connects=99, name="primary")
    secondary = FakeQuoteStreamProvider(name="secondary")
    session = _session(primary, secondary, clock=clock)
    assert session.start() == "streaming"
    assert session.source is secondary
    assert secondary.subscribed == dict(SYMBOLS)


def test_cooldown_prevents_flapping_and_primary_returns_after_it() -> None:
    clock = Clock(_at(13, 25))  # after continuous trading: no staleness checks here
    primary = FakeQuoteStreamProvider(name="primary")
    secondary = FakeQuoteStreamProvider(name="secondary")
    session = _session(primary, secondary, clock=clock)
    session.start()

    primary.fail_connects = 99  # the primary drops and cannot come back for now
    primary.drop()
    session.ensure()
    assert session.source is secondary
    connects = primary.connects

    clock.advance(299)  # inside the cooldown: no attempt on the primary
    session.ensure()
    assert (primary.connects, session.source) == (connects, secondary)

    clock.advance(2)  # cooldown over, primary still down: one attempt, stay put
    session.ensure()
    assert (primary.connects, session.source) == (connects + 1, secondary)
    assert secondary.is_connected()

    primary.fail_connects = 0  # primary recovers, but the next try waits a full cooldown
    clock.advance(60)
    session.ensure()
    assert session.source is secondary
    clock.advance(300)
    session.ensure()
    assert session.source is primary
    assert primary.subscribed == dict(SYMBOLS)
    assert not secondary.is_connected()
    assert session.fallbacks == 1


def test_polling_retries_the_primary_after_the_cooldown() -> None:
    clock = Clock(_at(10, 0))
    fake = FakeQuoteStreamProvider(fail_connects=3)  # all three start attempts fail
    session = _session(fake, clock=clock)
    assert session.start() == "polling"
    clock.advance(301)
    assert session.ensure() == "streaming"
    assert fake.subscribed == dict(SYMBOLS)


def test_silent_feed_reconnects_once_then_falls_back() -> None:
    clock = Clock(_at(10, 0))
    fake = FakeQuoteStreamProvider()
    session = _session(fake, clock=clock)
    session.start()

    clock.advance(100)
    fake.push("2330", clock.now, price=D(100), volume=1)
    clock.advance(100)  # 100 s since the last message: still fresh
    assert session.ensure() == "streaming"
    assert fake.connects == 1

    clock.advance(30)  # 130 s: stale -> reconnect
    assert session.ensure() == "streaming"
    assert (fake.connects, session.reconnects) == (2, 1)

    clock.advance(121)  # the new session is silent too -> give up on it
    assert session.ensure() == "polling"
    assert session.fallbacks == 1


def test_messages_after_a_stale_reconnect_clear_the_strike() -> None:
    clock = Clock(_at(10, 0))
    fake = FakeQuoteStreamProvider()
    session = _session(fake, clock=clock)
    session.start()
    clock.advance(121)
    session.ensure()  # stale -> reconnect
    clock.advance(10)
    fake.push("2330", clock.now, price=D(100), volume=1)
    clock.advance(121)
    assert session.ensure() == "streaming"  # stale again, but it had recovered: reconnect
    assert fake.connects == 3


def test_quiet_feed_is_normal_in_the_closing_auction() -> None:
    clock = Clock(_at(13, 24))
    fake = FakeQuoteStreamProvider()
    session = _session(fake, clock=clock)
    session.start()
    clock.advance(5 * 60)  # 13:29, no trades during the call auction
    assert session.ensure() == "streaming"
    assert fake.connects == 1


def test_symbol_changes_subscribe_the_difference() -> None:
    clock = Clock(_at(10, 0))
    fake = FakeQuoteStreamProvider()
    session = _session(fake, clock=clock)
    session.start()
    session.set_symbols([("2330", "twse"), ("2454", "twse")])
    assert fake.subscribed == {"2330": "twse", "2454": "twse"}
    assert session.streamed == {"2330", "2454"}


def test_symbols_beyond_the_limit_are_left_to_polling() -> None:
    clock = Clock(_at(10, 0))
    fake = FakeQuoteStreamProvider(max_subscriptions=2)
    session = _session(fake, clock=clock)
    session.start()
    assert session.streamed == {"0050", "2317"}  # sorted, first two


def test_late_loss_callback_from_a_dropped_source_is_ignored() -> None:
    clock = Clock(_at(10, 0))
    primary = FakeQuoteStreamProvider(name="primary")
    secondary = FakeQuoteStreamProvider(name="secondary")
    session = _session(primary, secondary, clock=clock)
    session.start()
    primary.fail_connects = 99
    primary.drop()
    session.ensure()
    assert session.source is secondary
    primary.drop("late callback")  # must not tear down the secondary
    session.ensure()
    assert session.source is secondary
    assert secondary.connects == 1


def test_drained_messages_are_grouped_by_source() -> None:
    clock = Clock(_at(10, 0))
    fake = FakeQuoteStreamProvider()
    session = _session(fake, clock=clock)
    session.start()
    fake.push("2330", _at(10, 0, 1), price=D(100), volume=1)
    fake.push("0050", _at(10, 0, 2), price=D(50), volume=1)
    drained = session.drain()
    assert list(drained) == ["fake_stream"]
    assert len(drained["fake_stream"]) == 2
    assert session.drain() == {}
    session.close()
    assert not fake.is_connected()


# ----------------------------------------------------------------------------- job


class RecordingNotifier(Notifier):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, Severity]] = []

    def send(self, subject: str, body: str, severity: Severity = "warning") -> None:
        self.sent.append((subject, body, severity))


@pytest.fixture
def tsmc(clean_db: Engine) -> Iterator[int]:
    with clean_db.begin() as conn:
        stock_id: int = conn.execute(
            text(
                "INSERT INTO stocks (symbol, market, type, name, listed_date) "
                "VALUES ('2330', 'twse', 'stock', '台積電', '1994-09-05') RETURNING id"
            )
        ).scalar_one()
        conn.execute(text("INSERT INTO watchlist (stock_id) VALUES (:id)"), {"id": stock_id})
    yield stock_id
    with clean_db.begin() as conn:
        conn.execute(text("TRUNCATE stocks RESTART IDENTITY CASCADE"))


def _run(
    engine: Engine,
    tmp_path: Path,
    clock: Clock,
    stream: FakeQuoteStreamProvider,
    notifier: Notifier,
    **params: Any,
) -> JobRunResult:
    store = LocalRawStore(engine, tmp_path)
    client = make_client(httpx.MockTransport(official_handler))
    registry = ProviderRegistry({"quote": [TwseMisProvider(client)], "quote_stream": [stream]})
    router = ProviderRouter(
        registry,
        store,
        retry=RetryPolicy(max_attempts=1, base_delay=0, jitter=0),
        limiter=RateLimiter(clock=lambda: 0.0, sleep=lambda _: None),
        sleep=lambda _: None,
    )
    return run_job(
        "poll_quotes",
        params,
        engine=engine,
        rawstore=store,
        notifier=notifier,
        router=router,
        job_factory=lambda cls: PollQuotesJob(
            now=lambda: clock.now, sleep=clock.sleep, policy=POLICY
        ),
    )


def test_job_streams_lands_raw_and_writes_each_round(
    clean_db: Engine, tmp_path: Path, tsmc: int
) -> None:
    # The MIS fixture is the 13:30 snapshot, so the stream runs after it.
    clock = Clock(_at(13, 31))
    fake = FakeQuoteStreamProvider()

    def feed() -> None:
        if clock.now == _at(13, 31, 30):
            fake.push("2330", _at(13, 31, 10), price=D(2425), volume=33_300_000)
            fake.push("2330", _at(13, 31, 11), kind="bidask", bid=D(2425), ask=D(2430))

    clock.on_sleep = feed
    notifier = RecordingNotifier()
    result = _run(clean_db, tmp_path, clock, fake, notifier, until="13:32")
    assert result.status == "succeeded", result.error
    assert result.message == "1 檔，3 輪（串流 fake_stream 3 輪）"
    assert notifier.sent == []
    assert not fake.is_connected()  # closed at the end

    with clean_db.connect() as conn:
        row = conn.execute(
            text(
                "SELECT q.price, q.prev_close, q.bid, q.volume, q.source, q.quote_time, "
                "r.provider, r.dataset FROM quotes_latest q JOIN raw_objects r "
                "ON r.id = q.raw_object_id"
            )
        ).one()
    # Price and bid/ask from the stream; the reference price kept from the first poll.
    assert (row.price, row.prev_close, row.bid, row.volume) == (
        D(2425),
        D(2440),
        D(2425),
        33_300_000,
    )
    assert (row.source, row.provider, row.dataset) == ("fake_stream", "fake_stream", "quote_stream")
    assert row.quote_time == _at(13, 31, 11).astimezone(UTC)

    with clean_db.connect() as conn:
        samples = conn.execute(
            text("SELECT sampled_at, price, source FROM quotes_intraday ORDER BY sampled_at")
        ).all()
    # One sample per round on the 30 s grid: the polled 13:30 snapshot, then the stream.
    assert [(s.sampled_at, s.price, s.source) for s in samples] == [
        (_at(13, 31).astimezone(UTC), D(2420), "twse_mis"),
        (_at(13, 31, 30).astimezone(UTC), D(2425), "fake_stream"),
        (_at(13, 32).astimezone(UTC), D(2425), "fake_stream"),
    ]


def test_job_polls_and_notifies_once_when_the_stream_is_down(
    clean_db: Engine, tmp_path: Path, tsmc: int
) -> None:
    clock = Clock(_at(13, 31))
    fake = FakeQuoteStreamProvider(fail_connects=99, permanent=True)
    notifier = RecordingNotifier()
    result = _run(clean_db, tmp_path, clock, fake, notifier, until="13:32")
    assert result.status == "succeeded", result.error
    assert result.message == "1 檔，3 輪（串流 fake_stream 0 輪，改用備援 1 次）"
    assert [s for s, _, _ in notifier.sent] == ["盤中報價改用輪詢"]
    with clean_db.connect() as conn:
        assert conn.execute(text("SELECT source FROM quotes_latest")).scalar_one() == "twse_mis"


def test_mode_poll_ignores_the_stream(clean_db: Engine, tmp_path: Path, tsmc: int) -> None:
    clock = Clock(_at(13, 31))
    fake = FakeQuoteStreamProvider()
    result = _run(clean_db, tmp_path, clock, fake, RecordingNotifier(), until="13:31", mode="poll")
    assert result.message == "1 檔，輪詢 1 次"
    assert fake.connects == 0
