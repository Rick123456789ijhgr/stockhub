"""Intraday quotes for the watchlist and holdings (plan: every 30 s during the session).

One run covers one trading day: Cloud Scheduler starts it before the open and it runs
until `until` (default 13:35 Taipei, after the closing auction). `once=true` takes a single
snapshot, e.g. for a manual refresh or outside trading hours.

With PROVIDERS_QUOTE_STREAM set, the run keeps one stream session open instead and writes
what it received every `interval` (D-123); the first round, symbols beyond the stream's
subscription limit and any time no stream works are polled from PROVIDERS_QUOTE.
`mode=poll` forces polling.

Every round also stores one sample per stock in quotes_intraday (the day's chart); a run
first deletes samples older than QUOTE_INTRADAY_KEEP_DAYS trading days (D-124).
"""

from __future__ import annotations

import logging
import time as time_module
from collections.abc import Callable, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any, ClassVar

from sqlalchemy import Connection, text

from stockhub.common.portfolio_store import holdings
from stockhub.common.settings import get_settings
from stockhub.common.timeutil import TAIPEI, taipei_today, utcnow
from stockhub.common.trading_calendar import is_trading_day
from stockhub.etl.jobs.alerts import check_holding_moves
from stockhub.etl.jobs.base import Job, JobContext, JobOutcome, register_job
from stockhub.etl.providers.base import Market, Quote, QuoteProvider, StreamMessage
from stockhub.etl.providers.router import ProviderRouter
from stockhub.etl.quote_stream import LatestQuotes, QuoteStreamSession, StreamPolicy

log = logging.getLogger(__name__)

DEFAULT_INTERVAL = 30.0
DEFAULT_UNTIL = time(13, 35)
SESSION_OPEN = time(9, 0)
BATCH = QuoteProvider.max_symbols
REFRESH_ROUNDS = 10
"""Re-read the watchlist and holdings every this many rounds (5 min at 30 s), so a stock
added during the session gets quotes the same day."""


def polled_stocks(
    conn: Connection, extra: Sequence[str] = (), today: date | None = None
) -> list[tuple[int, str, Market]]:
    """Active stocks on the watchlist, held (replayed with splits, reductions and stock
    dividends) or named explicitly."""
    held = list(holdings(conn, today or taipei_today()))
    rows = conn.execute(
        text(
            "SELECT s.id, s.symbol, s.market FROM stocks s "
            "WHERE s.delisted_date IS NULL AND ("
            "  s.id IN (SELECT stock_id FROM watchlist)"
            "  OR s.id = ANY(:held)"
            "  OR s.symbol = ANY(:extra)) "
            "ORDER BY s.symbol"
        ),
        {"extra": list(extra), "held": held},
    ).all()
    return [(r.id, r.symbol, r.market) for r in rows]


def store_quotes(
    conn: Connection,
    quotes: Sequence[Quote],
    ids: dict[str, int],
    source: str,
    raw_object_id: int | None,
) -> int:
    """Upsert the latest snapshot per stock; returns how many rows changed.

    A tick without a last trade (or without open/high/low/reference, as a stream that
    started mid-session may be) keeps the value seen earlier the same day, and an older
    snapshot never replaces a newer one.
    """
    changed = 0
    for q in quotes:
        stock_id = ids.get(q.symbol)
        if stock_id is None:
            continue
        changed += conn.execute(
            text(
                "INSERT INTO quotes_latest AS cur (stock_id, trade_date, quote_time, price, open, "
                "high, low, prev_close, volume, bid, ask, source, raw_object_id) "
                "VALUES (:stock_id, :trade_date, :at, :price, :open, :high, :low, :prev_close, "
                ":volume, :bid, :ask, :source, :raw_object_id) "
                "ON CONFLICT (stock_id) DO UPDATE SET trade_date = excluded.trade_date, "
                "quote_time = excluded.quote_time, "
                "price = CASE WHEN excluded.price IS NULL AND cur.trade_date = excluded.trade_date "
                "        THEN cur.price ELSE excluded.price END, "
                "open = " + _same_day("open") + ", high = " + _same_day("high") + ", "
                "low = " + _same_day("low") + ", prev_close = " + _same_day("prev_close") + ", "
                "volume = excluded.volume, bid = excluded.bid, "
                "ask = excluded.ask, source = excluded.source, "
                "raw_object_id = excluded.raw_object_id, fetched_at = now() "
                "WHERE excluded.quote_time > cur.quote_time "
                "OR (excluded.quote_time = cur.quote_time AND excluded.volume <> cur.volume)"
            ),
            {
                "stock_id": stock_id,
                "trade_date": q.trade_date,
                "at": q.at,
                "price": q.price,
                "open": q.open,
                "high": q.high,
                "low": q.low,
                "prev_close": q.prev_close,
                "volume": q.volume,
                "bid": q.bid,
                "ask": q.ask,
                "source": source,
                "raw_object_id": raw_object_id,
            },
        ).rowcount
    return changed


def store_samples(
    conn: Connection,
    entries: Sequence[tuple[Quote, str]],
    ids: dict[str, int],
    sampled_at: datetime,
    today: date,
) -> int:
    """One quotes_intraday row per stock that has traded today; reruns add nothing."""
    rows = [
        {
            "stock_id": ids[q.symbol],
            "sampled_at": sampled_at,
            "trade_date": q.trade_date,
            "quote_time": q.at,
            "price": q.price,
            "volume": q.volume,
            "bid": q.bid,
            "ask": q.ask,
            "source": source,
        }
        for q, source in entries
        if q.symbol in ids and q.trade_date == today and q.price is not None
    ]
    if not rows:
        return 0
    result = conn.execute(
        text(
            "INSERT INTO quotes_intraday (stock_id, sampled_at, trade_date, quote_time, price, "
            "volume, bid, ask, source) VALUES (:stock_id, :sampled_at, :trade_date, "
            ":quote_time, :price, :volume, :bid, :ask, :source) "
            "ON CONFLICT (stock_id, sampled_at) DO NOTHING"
        ),
        rows,
    )
    return result.rowcount


def prune_samples(conn: Connection, today: date, keep_days: int) -> int:
    """Delete samples older than the latest `keep_days` trading days up to today."""
    return conn.execute(
        text(
            "DELETE FROM quotes_intraday WHERE trade_date < ("
            "  SELECT min(date) FROM ("
            "    SELECT date FROM trading_calendar WHERE is_trading_day AND date <= :today "
            "    ORDER BY date DESC LIMIT :keep) recent)"
        ),
        {"today": today, "keep": keep_days},
    ).rowcount


def _same_day(column: str) -> str:
    return (
        f"CASE WHEN excluded.{column} IS NULL AND cur.trade_date = excluded.trade_date "
        f"THEN cur.{column} ELSE excluded.{column} END"
    )


def _time_param(value: Any, default: time) -> time:
    return time.fromisoformat(str(value)) if value else default


@register_job
class PollQuotesJob(Job):
    name: ClassVar[str] = "poll_quotes"
    description: ClassVar[str] = (
        "Intraday quotes for watchlist + holdings: stream (PROVIDERS_QUOTE_STREAM) or poll "
        "(params: symbols, interval, until, once, mode=poll)"
    )
    uses_date: ClassVar[bool] = False
    timeout: ClassVar[timedelta] = timedelta(hours=6)

    def __init__(
        self,
        now: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], None] = time_module.sleep,
        policy: StreamPolicy | None = None,
        keep_days: int | None = None,
    ) -> None:
        self.now, self.sleep = now, sleep
        self.policy = policy
        self.keep_days = keep_days

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        extra = [s.strip() for s in str(ctx.params.get("symbols") or "").split(",") if s.strip()]
        interval = float(ctx.params.get("interval") or DEFAULT_INTERVAL)
        until = _time_param(ctx.params.get("until"), DEFAULT_UNTIL)
        once = str(ctx.params.get("once", "")).lower() in {"1", "true", "yes"}
        streams = [] if once or ctx.params.get("mode") == "poll" else router.quote_streams()

        today = self.now().astimezone(TAIPEI).date()
        with ctx.engine.connect() as conn:
            targets = polled_stocks(conn, extra, today)
            trading = is_trading_day(conn, today)
        if not targets:
            return JobOutcome("skipped", "沒有自選股或持股，也沒有指定 symbols")
        if not trading and not once:
            return JobOutcome("skipped", f"{today} 不是交易日")

        run = _QuoteRun(ctx, router, targets, extra, today)
        run.prune(self.keep_days or get_settings().quote_intraday_keep_days)
        session = None
        if streams:
            policy = self.policy or StreamPolicy.from_settings(get_settings())
            session = QuoteStreamSession(streams, policy, self.now, self.sleep)
        rounds = 0
        try:
            while True:
                started = self.now()
                local = started.astimezone(TAIPEI).time()
                if not once and local < SESSION_OPEN:
                    self.sleep(min(interval, _seconds_until(started, SESSION_OPEN)))
                    continue
                if rounds and rounds % REFRESH_ROUNDS == 0:
                    run.refresh()
                if session is None:
                    run.poll(run.requests)
                else:
                    run.stream_round(session, first=rounds == 0)
                if not once:
                    run.sample(started)
                run.check_alerts()
                rounds += 1
                if once or local >= until:
                    break
                elapsed = (self.now() - started).total_seconds()
                self.sleep(max(0.0, interval - elapsed))
        finally:
            if session is not None:
                session.close()
        return JobOutcome(message=run.summary(rounds, session))


class _QuoteRun:
    """State of one poll_quotes run: targets, the merged cache and counters."""

    def __init__(
        self,
        ctx: JobContext,
        router: ProviderRouter,
        targets: list[tuple[int, str, Market]],
        extra: list[str],
        today: date,
    ) -> None:
        self.ctx, self.router, self.extra, self.today = ctx, router, extra, today
        self.cache = LatestQuotes()
        self.alerts = 0
        self.streamed_rounds = 0
        self.parse_errors = 0
        self.notified_fallback = False
        self.samples = 0
        self._set_targets(targets)

    def _set_targets(self, targets: list[tuple[int, str, Market]]) -> None:
        self.targets = targets
        self.ids = {symbol: stock_id for stock_id, symbol, _ in targets}
        self.requests = [(symbol, market) for _, symbol, market in targets]

    def refresh(self) -> None:
        """Pick up watchlist and holding changes made during the session."""
        try:
            with self.ctx.engine.connect() as conn:
                targets = polled_stocks(conn, self.extra, self.today)
        except Exception:
            log.exception("could not re-read the quote targets")
            return
        if targets and targets != self.targets:
            log.info("quote targets changed: %d -> %d", len(self.targets), len(targets))
            self._set_targets(targets)

    def poll(self, requests: Sequence[tuple[str, Market]]) -> None:
        for i in range(0, len(requests), BATCH):
            fetched = self.router.quotes(requests[i : i + BATCH])
            with self.ctx.engine.begin() as conn:
                self.ctx.add_rows(
                    store_quotes(conn, fetched.items, self.ids, fetched.provider, fetched.raw.id)
                )
            for quote in fetched.items:
                self.cache.put(quote, fetched.provider, dirty=False)

    def stream_round(self, session: QuoteStreamSession, *, first: bool) -> None:
        """Keep the stream up, land and apply what it sent, poll what it does not cover.

        The first round always polls too: it fills open, high, low and the reference price,
        which a stream joining mid-session may never send.
        """
        session.set_symbols(self.requests)
        mode = session.ensure()
        raw_ids = self._land(session)
        if mode == "streaming":
            self.streamed_rounds += 1
        elif not self.notified_fallback:
            self._notify_fallback(session)
        streamed = session.streamed
        missing = [r for r in self.requests if first or r[0] not in streamed]
        if missing:
            self.poll(missing)
        changed = self.cache.take_dirty()
        with self.ctx.engine.begin() as conn:
            for source, quotes in changed.items():
                self.ctx.add_rows(store_quotes(conn, quotes, self.ids, source, raw_ids.get(source)))

    def _land(self, session: QuoteStreamSession) -> dict[str, int]:
        """Store each source's buffered messages as one raw object, then parse them."""
        raw_ids: dict[str, int] = {}
        for name, messages in session.drain().items():
            if not messages:
                continue
            raw = self.ctx.rawstore.put(
                name,
                "quote_stream",
                {"messages": [_message_json(m) for m in messages]},
                params={
                    "count": len(messages),
                    "from": messages[0].received_at.isoformat(),
                    "to": messages[-1].received_at.isoformat(),
                },
            )
            raw_ids[name] = raw.id
            provider = session.provider(name)
            for message in messages:
                try:
                    updates = provider.parse_message(message)
                except Exception as exc:
                    self.parse_errors += 1
                    log.error("%s could not parse a message in %s: %s", name, raw.uri, exc)
                    continue
                for update in updates:
                    if update.symbol in self.ids:
                        self.cache.apply(update, name)
        return raw_ids

    def _notify_fallback(self, session: QuoteStreamSession) -> None:
        self.notified_fallback = True
        names = "、".join(p.name for p in session.streams)
        try:
            self.ctx.notifier.send(
                "盤中報價改用輪詢",
                f"串流來源（{names}）連不上或沒有資料，盤中報價改用 PROVIDERS_QUOTE 輪詢；"
                "冷卻時間過後會再試主來源。詳見任務 poll_quotes 的記錄。",
                severity="warning",
            )
        except Exception:
            log.exception("could not send the quote fallback notice")

    def sample(self, at: datetime) -> None:
        """This round's latest quote per stock into quotes_intraday (the day's chart)."""
        with self.ctx.engine.begin() as conn:
            self.samples += store_samples(
                conn, self.cache.entries(), self.ids, at.replace(microsecond=0), self.today
            )

    def prune(self, keep_days: int) -> None:
        try:
            with self.ctx.engine.begin() as conn:
                pruned = prune_samples(conn, self.today, keep_days)
        except Exception:
            log.exception("could not prune quotes_intraday")
            return
        if pruned:
            log.info("pruned %d intraday samples (keeping %d trading days)", pruned, keep_days)

    def check_alerts(self) -> None:
        """Holding alerts after each round; a failure here must not stop the quotes."""
        try:
            with self.ctx.engine.begin() as conn:
                self.alerts += check_holding_moves(conn, self.ctx.notifier, self.today)
        except Exception:
            log.exception("holding alert check failed")

    def summary(self, rounds: int, session: QuoteStreamSession | None) -> str:
        if session is None:
            out = f"{len(self.targets)} 檔，輪詢 {rounds} 次"
        else:
            names = "、".join(p.name for p in session.streams)
            out = f"{len(self.targets)} 檔，{rounds} 輪（串流 {names} {self.streamed_rounds} 輪"
            if session.reconnects:
                out += f"，重新連線 {session.reconnects} 次"
            if session.fallbacks:
                out += f"，改用備援 {session.fallbacks} 次"
            if self.parse_errors:
                out += f"，無法解析 {self.parse_errors} 則"
            out += "）"
        return out + (f"，持股警示 {self.alerts} 則" if self.alerts else "")


def _message_json(message: StreamMessage) -> dict[str, Any]:
    return {
        "dataset": message.dataset,
        "received_at": message.received_at.isoformat(),
        "payload": message.payload,
    }


def _seconds_until(now: datetime, at: time) -> float:
    local = now.astimezone(TAIPEI)
    target = local.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    return max(1.0, (target - local).total_seconds())
