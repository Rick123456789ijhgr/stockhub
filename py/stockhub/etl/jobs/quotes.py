"""Intraday quotes for the watchlist and holdings (plan: every 30 s during the session).

One run covers one trading day: Cloud Scheduler starts it before the open and it polls
until `until` (default 13:35 Taipei, after the closing auction). `once=true` takes a single
snapshot, e.g. for a manual refresh or outside trading hours.
"""

from __future__ import annotations

import logging
import time as time_module
from collections.abc import Callable, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any, ClassVar

from sqlalchemy import Connection, text

from stockhub.common.portfolio_store import holdings
from stockhub.common.timeutil import TAIPEI, taipei_today, utcnow
from stockhub.common.trading_calendar import is_trading_day
from stockhub.etl.jobs.alerts import check_holding_moves
from stockhub.etl.jobs.base import Job, JobContext, JobOutcome, register_job
from stockhub.etl.providers.base import Market, Quote, QuoteProvider

log = logging.getLogger(__name__)

DEFAULT_INTERVAL = 30.0
DEFAULT_UNTIL = time(13, 35)
SESSION_OPEN = time(9, 0)
BATCH = QuoteProvider.max_symbols


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

    A tick without a last trade keeps the price seen earlier the same day, and an older
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
                "open = excluded.open, high = excluded.high, low = excluded.low, "
                "prev_close = excluded.prev_close, volume = excluded.volume, bid = excluded.bid, "
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


def _time_param(value: Any, default: time) -> time:
    return time.fromisoformat(str(value)) if value else default


@register_job
class PollQuotesJob(Job):
    name: ClassVar[str] = "poll_quotes"
    description: ClassVar[str] = (
        "Poll intraday quotes for watchlist + holdings (params: symbols, interval, until, once)"
    )
    uses_date: ClassVar[bool] = False
    timeout: ClassVar[timedelta] = timedelta(hours=6)

    def __init__(
        self,
        now: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], None] = time_module.sleep,
    ) -> None:
        self.now, self.sleep = now, sleep

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        extra = [s.strip() for s in str(ctx.params.get("symbols") or "").split(",") if s.strip()]
        interval = float(ctx.params.get("interval") or DEFAULT_INTERVAL)
        until = _time_param(ctx.params.get("until"), DEFAULT_UNTIL)
        once = str(ctx.params.get("once", "")).lower() in {"1", "true", "yes"}

        today = self.now().astimezone(TAIPEI).date()
        with ctx.engine.connect() as conn:
            targets = polled_stocks(conn, extra, today)
            trading = is_trading_day(conn, today)
        if not targets:
            return JobOutcome("skipped", "沒有自選股或持股，也沒有指定 symbols")
        if not trading and not once:
            return JobOutcome("skipped", f"{today} 不是交易日")

        ids = {symbol: stock_id for stock_id, symbol, _ in targets}
        requests = [(symbol, market) for _, symbol, market in targets]
        rounds = 0
        alerts = 0
        while True:
            started = self.now()
            local = started.astimezone(TAIPEI).time()
            if not once and local < SESSION_OPEN:
                self.sleep(min(interval, _seconds_until(started, SESSION_OPEN)))
                continue
            for i in range(0, len(requests), BATCH):
                fetched = router.quotes(requests[i : i + BATCH])
                with ctx.engine.begin() as conn:
                    ctx.add_rows(
                        store_quotes(conn, fetched.items, ids, fetched.provider, fetched.raw.id)
                    )
            alerts += self._check_alerts(ctx, today)
            rounds += 1
            if once or local >= until:
                break
            elapsed = (self.now() - started).total_seconds()
            self.sleep(max(0.0, interval - elapsed))
        note = f"，持股警示 {alerts} 則" if alerts else ""
        return JobOutcome(message=f"{len(targets)} 檔，輪詢 {rounds} 次{note}")

    @staticmethod
    def _check_alerts(ctx: JobContext, today: date) -> int:
        """Holding alerts after each poll; a failure here must not stop the quotes."""
        try:
            with ctx.engine.begin() as conn:
                return check_holding_moves(conn, ctx.notifier, today)
        except Exception:
            log.exception("holding alert check failed")
            return 0


def _seconds_until(now: datetime, at: time) -> float:
    local = now.astimezone(TAIPEI)
    target = local.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    return max(1.0, (target - local).total_seconds())
