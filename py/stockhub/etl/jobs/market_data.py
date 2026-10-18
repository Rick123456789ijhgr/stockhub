"""Market data jobs: trading calendar, stock master, daily prices and their backfill.

All writes are idempotent upserts; raw responses are landed by the ProviderRouter.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, ClassVar, Literal

from sqlalchemy import Connection, text

from stockhub.common.db import upsert
from stockhub.common.timeutil import taipei_today, utcnow
from stockhub.common.trading_calendar import is_trading_day, trading_days_between
from stockhub.etl.jobs.base import Job, JobContext, JobError, JobOutcome, register_job
from stockhub.etl.providers.base import CalendarEntry, DailyBar, Delisting, Market, Security
from stockhub.etl.quality import check_daily_bar

log = logging.getLogger(__name__)

MARKETS: tuple[Market, ...] = ("twse", "tpex")
PRICE_COLUMNS = ["open", "high", "low", "close", "volume", "turnover", "source"]


# ----------------------------------------------------------------------------- calendar


def calendar_rows(year: int, entries: Iterable[CalendarEntry]) -> list[dict[str, Any]]:
    """Every date of `year`: weekdays trade unless announced closed; announced dates win."""
    special = {e.day: e for e in entries if e.day.year == year}
    rows = []
    day = date(year, 1, 1)
    while day.year == year:
        entry = special.get(day)
        if entry is not None:
            rows.append({"date": day, "is_trading_day": entry.is_trading_day, "note": entry.name})
        else:
            trading = day.isoweekday() < 6
            rows.append({"date": day, "is_trading_day": trading, "note": f"official:{year}"})
        day += timedelta(days=1)
    return rows


@register_job
class SyncCalendarJob(Job):
    name: ClassVar[str] = "sync_calendar"
    description: ClassVar[str] = "Import the TWSE holiday schedule (params: start_year, end_year)"
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        this_year = taipei_today().year
        start = int(ctx.params.get("start_year", this_year))
        end = int(ctx.params.get("end_year", start))
        first = int((ctx.checkpoint or {}).get("next_year", start))
        published, missing = [], []
        for year in range(first, end + 1):
            entries = router.calendar(year).items
            if not entries:
                missing.append(year)
            else:
                with ctx.engine.begin() as conn:
                    ctx.add_rows(
                        upsert(conn, "trading_calendar", calendar_rows(year, entries), ["date"])
                    )
                published.append(year)
            ctx.save_checkpoint({"next_year": year + 1})
        message = f"已匯入：{published or '無'}；尚未公布（保留原本日曆）：{missing or '無'}"
        return JobOutcome(message=message)


# ----------------------------------------------------------------------------- stock master


def _sync_market_securities(conn: Connection, market: Market, securities: list[Security]) -> int:
    """Upsert one market's master list; an active row with the same symbol is updated in place."""
    active = {
        r.symbol: r
        for r in conn.execute(
            text(
                "SELECT id, symbol, name, type, listed_date, industry FROM stocks "
                "WHERE delisted_date IS NULL"
            )
        )
    }
    changed = 0
    for sec in securities:
        current = active.get(sec.symbol)
        values = {
            "symbol": sec.symbol,
            "market": market,
            "type": sec.type,
            "name": sec.name,
            "listed_date": sec.listed_date,
            "industry": sec.industry,
        }
        if current is None:
            conn.execute(
                text(
                    "INSERT INTO stocks (symbol, market, type, name, listed_date, industry) "
                    "VALUES (:symbol, :market, :type, :name, :listed_date, :industry) "
                    "ON CONFLICT (symbol, listed_date) DO NOTHING"
                ),
                values,
            )
            changed += 1
        elif (current.name, current.type, current.listed_date, current.industry) != (
            sec.name,
            sec.type,
            sec.listed_date,
            sec.industry,
        ):
            conn.execute(
                text(
                    "UPDATE stocks SET market = :market, type = :type, name = :name, "
                    "listed_date = :listed_date, industry = :industry WHERE id = :id"
                ),
                {**values, "id": current.id},
            )
            changed += 1
    return changed


@register_job
class SyncStocksJob(Job):
    name: ClassVar[str] = "sync_stocks"
    description: ClassVar[str] = "Import listed/OTC stocks and ETFs from the ISIN master lists"
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        counts = []
        for market in MARKETS:
            securities = router.securities(market).items
            with ctx.engine.begin() as conn:
                ctx.add_rows(_sync_market_securities(conn, market, securities))
            counts.append(f"{market} {len(securities)} 檔")
        # Stocks that left the lists are closed by sync_delistings (official delisting dates).
        return JobOutcome(message="主檔：" + "、".join(counts))


# ----------------------------------------------------------------------------- delistings

TWSE_OPENING = date(1962, 2, 9)
"""Earliest possible listing date; placeholder until the first stored price refines it."""
TRANSFER_WINDOW = (timedelta(days=-7), timedelta(days=30))
"""A same-symbol listing on the other market this close to a delisting is a market transfer."""


@dataclass
class DelistingStats:
    inserted: int = 0
    closed: int = 0
    transfers: int = 0
    unchanged: int = 0

    def __str__(self) -> str:
        return (
            f"新增下市 {self.inserted}、現役改標下市 {self.closed}、"
            f"轉市場略過 {self.transfers}、已存在 {self.unchanged}"
        )


def apply_delisting(conn: Connection, item: Delisting, stats: DelistingStats) -> None:
    """Record one delisting idempotently, keeping one row per listing incarnation.

    - same symbol already delisted on that date: nothing to do;
    - the symbol is active on the other market and was listed around that date: it moved
      market (e.g. 上櫃轉上市), the stock lives on;
    - active on the same market and listed before that date: close that row;
    - a delisted row on the other market already spans that date (its estimated listing
      starts earlier): the company moved market before that delisting, nothing to add;
    - the latest earlier incarnation was delisted from the other market: the company moved
      market (both directions happen, e.g. 上櫃轉上市 or 下市改列上櫃) and traded there until
      this date, so that row is extended instead of starting a second id;
    - otherwise it is an earlier incarnation we never stored: insert it with an estimated
      listing date (the delisting lists carry none).
    """
    rows = conn.execute(
        text(
            "SELECT id, market, listed_date, listed_date_estimated, delisted_date FROM stocks "
            "WHERE symbol = :s ORDER BY listed_date"
        ),
        {"s": item.symbol},
    ).all()
    if any(r.delisted_date == item.delisted_date for r in rows):
        stats.unchanged += 1
        return
    if any(
        r.market != item.market
        and r.listed_date_estimated
        and r.listed_date < item.delisted_date < r.delisted_date
        for r in rows
        if r.delisted_date is not None
    ):
        stats.transfers += 1
        return
    lo, hi = TRANSFER_WINDOW
    for r in rows:
        if r.delisted_date is not None:
            continue
        if r.market != item.market and item.delisted_date + lo <= r.listed_date <= (
            item.delisted_date + hi
        ):
            stats.transfers += 1
            return
        if r.market == item.market and r.listed_date < item.delisted_date:
            conn.execute(
                text(
                    "UPDATE stocks SET delisted_date = :d, delisting_reason = :reason "
                    "WHERE id = :id"
                ),
                {"d": item.delisted_date, "reason": item.reason, "id": r.id},
            )
            stats.closed += 1
            return
    earlier = [
        r for r in rows if r.delisted_date is not None and r.delisted_date < item.delisted_date
    ]
    latest = max(earlier, key=lambda r: r.delisted_date, default=None)
    if latest is not None and latest.market != item.market and latest.listed_date_estimated:
        conn.execute(
            text(
                "UPDATE stocks SET market = :market, name = :name, delisted_date = :d, "
                "delisting_reason = :reason WHERE id = :id"
            ),
            {
                "market": item.market,
                "name": item.name,
                "d": item.delisted_date,
                "reason": item.reason,
                "id": latest.id,
            },
        )
        stats.transfers += 1
        return
    result = conn.execute(
        text(
            "INSERT INTO stocks (symbol, market, type, name, listed_date, delisted_date, "
            "listed_date_estimated, delisting_reason) "
            "VALUES (:symbol, :market, :type, :name, :listed, :delisted, true, :reason) "
            "ON CONFLICT (symbol, listed_date) DO NOTHING"
        ),
        {
            "symbol": item.symbol,
            "market": item.market,
            "type": "etf" if item.symbol.startswith("00") else "stock",
            "name": item.name,
            "listed": latest.delisted_date if latest is not None else TWSE_OPENING,
            "delisted": item.delisted_date,
            "reason": item.reason,
        },
    )
    if result.rowcount:
        stats.inserted += 1
    else:
        log.warning("could not insert delisting %s (listing date collision)", item)


def refine_estimated_listed_dates(conn: Connection) -> int:
    """Estimated listing dates become the first stored trading day once prices exist."""
    result = conn.execute(
        text(
            "UPDATE stocks s SET listed_date = f.first_day "
            "FROM (SELECT p.stock_id, min(p.trade_date) AS first_day FROM prices_daily p "
            "      WHERE p.stock_id IN (SELECT id FROM stocks WHERE listed_date_estimated) "
            "      GROUP BY p.stock_id) f "
            "WHERE s.id = f.stock_id AND s.listed_date_estimated "
            "AND s.listed_date IS DISTINCT FROM f.first_day"
        )
    )
    return result.rowcount


@register_job
class SyncDelistingsJob(Job):
    name: ClassVar[str] = "sync_delistings"
    description: ClassVar[str] = (
        "Import TWSE/TPEx delisted companies (params: start_year, end_year; default this year)"
    )
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        this_year = taipei_today().year
        start = int(ctx.params.get("start_year", this_year))
        end = int(ctx.params.get("end_year", this_year))
        first = int((ctx.checkpoint or {}).get("next_year", start))
        stats = DelistingStats()
        for year in range(first, end + 1):
            for market in MARKETS:
                items = router.delistings(market, year).items
                with ctx.engine.begin() as conn:
                    before = stats.inserted + stats.closed
                    for item in items:
                        apply_delisting(conn, item, stats)
                    ctx.add_rows(stats.inserted + stats.closed - before)
            ctx.save_checkpoint({"next_year": year + 1})
        with ctx.engine.begin() as conn:
            refined = refine_estimated_listed_dates(conn)
        ctx.add_rows(refined)
        return JobOutcome(message=f"{start}～{end}：{stats}；以首筆日線修正上市日 {refined}")


# ----------------------------------------------------------------------------- daily prices


@dataclass
class IngestStats:
    written: int = 0
    quarantined: int = 0
    unknown: int = 0
    received: int = 0

    def __str__(self) -> str:
        return (
            f"收到 {self.received}、寫入 {self.written}、隔離 {self.quarantined}、"
            f"非主檔代號略過 {self.unknown}"
        )


def stock_ids_on(conn: Connection, day: date) -> dict[str, int]:
    """symbol -> stock id of the listing alive on `day`.

    A reused symbol maps to the incarnation that ends first (the old one before its
    delisting, the new one after). The market is deliberately ignored: a stock that moved
    from TPEx to TWSE keeps one id, so its OTC history stays attached to it.
    """
    rows = conn.execute(
        text(
            "SELECT DISTINCT ON (symbol) symbol, id FROM stocks "
            "WHERE delisted_date IS NULL OR delisted_date > :d "
            "ORDER BY symbol, delisted_date NULLS LAST"
        ),
        {"d": day},
    ).all()
    return {r.symbol: r.id for r in rows}


def store_daily_bars(
    conn: Connection,
    bars: list[DailyBar],
    source: str,
    raw_object_id: int | None,
) -> IngestStats:
    """Write clean bars to prices_daily and failing ones to the quarantine table."""
    stats = IngestStats(received=len(bars))
    ids = {day: stock_ids_on(conn, day) for day in {bar.trade_date for bar in bars}}
    good: list[dict[str, Any]] = []
    bad: list[dict[str, Any]] = []
    now = utcnow()
    for bar in bars:
        stock_id = ids[bar.trade_date].get(bar.symbol)
        if stock_id is None:
            stats.unknown += 1
            continue
        reasons = check_daily_bar(bar)
        if reasons:
            bad.append(
                {
                    "stock_id": stock_id,
                    "trade_date": bar.trade_date,
                    "payload": json.dumps(bar.model_dump(mode="json")),
                    "reasons": reasons,
                    "source": source,
                    "raw_object_id": raw_object_id,
                }
            )
        else:
            good.append(
                {
                    "stock_id": stock_id,
                    "trade_date": bar.trade_date,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "turnover": bar.turnover,
                    "source": source,
                    "fetched_at": now,
                }
            )
    # fetched_at is set on insert only, so an unchanged rerun writes nothing.
    stats.written = upsert(conn, "prices_daily", good, ["stock_id", "trade_date"], PRICE_COLUMNS)
    for row in bad:
        conn.execute(
            text(
                "INSERT INTO prices_daily_quarantine "
                "(stock_id, trade_date, payload, reasons, source, raw_object_id) "
                "VALUES (:stock_id, :trade_date, CAST(:payload AS jsonb), :reasons, :source, "
                ":raw_object_id) ON CONFLICT (stock_id, trade_date, source) DO UPDATE SET "
                "payload = excluded.payload, reasons = excluded.reasons, "
                "raw_object_id = excluded.raw_object_id"
            ),
            row,
        )
    stats.quarantined = len(bad)
    return stats


DayResult = Literal["ingested", "closed"]


def ingest_day(ctx: JobContext, day: date) -> tuple[DayResult, str]:
    """Fetch and store both markets for one trading day.

    TWSE publishing nothing for a past weekday means the market was closed (e.g. before the
    official schedule existed, or an unannounced typhoon closure): the calendar is corrected.
    Only dates the schedule explicitly announced as trading days raise instead.
    """
    router = ctx.require_router()
    parts = []
    for market in MARKETS:
        fetched = router.daily_prices(day, market)
        if not fetched.items and market == "twse":
            return "closed", _handle_missing_day(ctx, day)
        with ctx.engine.begin() as conn:
            stats = store_daily_bars(conn, fetched.items, fetched.provider, fetched.raw.id)
        ctx.add_rows(stats.written)
        parts.append(f"{market}：{stats}")
    return "ingested", "；".join(parts)


def _handle_missing_day(ctx: JobContext, day: date) -> str:
    with ctx.engine.begin() as conn:
        note = conn.execute(
            text("SELECT note FROM trading_calendar WHERE date = :d"), {"d": day}
        ).scalar_one_or_none()
        if day >= taipei_today():
            raise JobError(f"{day} 的日線尚未公布，請收盤後（約 14:30 以後）再執行")
        if note is not None and not str(note).startswith(("seed:", "official:", "derived:")):
            raise JobError(f"官方公告 {day}（{note}）為交易日，但證交所沒有資料")
        conn.execute(
            text(
                "UPDATE trading_calendar SET is_trading_day = false, "
                "note = 'derived:no-twse-data' WHERE date = :d"
            ),
            {"d": day},
        )
    return f"{day} 證交所無資料，日曆改標為休市"


@register_job
class DailyPricesJob(Job):
    name: ClassVar[str] = "daily_prices"
    description: ClassVar[str] = "Fetch TWSE + TPEx daily quotes for --date (default today)"

    def run(self, ctx: JobContext) -> JobOutcome:
        _require_stocks(ctx)
        with ctx.engine.connect() as conn:
            if not is_trading_day(conn, ctx.run_date):
                return JobOutcome("skipped", f"{ctx.run_date} 不是交易日")
        result, message = ingest_day(ctx, ctx.run_date)
        return JobOutcome("skipped" if result == "closed" else "succeeded", message)


@register_job
class BackfillPricesJob(Job):
    name: ClassVar[str] = "backfill_prices"
    description: ClassVar[str] = "Daily quotes for every trading day in [start, end] (resumable)"
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        _require_stocks(ctx)
        end = date.fromisoformat(ctx.params.get("end") or taipei_today().isoformat())
        start = date.fromisoformat(
            ctx.params.get("start") or (end - timedelta(days=365)).isoformat()
        )
        resume = (ctx.checkpoint or {}).get("next")
        first = date.fromisoformat(resume) if resume else start
        with ctx.engine.connect() as conn:
            days = trading_days_between(conn, first, end)
        done = closed = 0
        for day in days:
            result, message = ingest_day(ctx, day)
            log.info("backfill %s %s", day, message)
            done += result == "ingested"
            closed += result == "closed"
            ctx.save_checkpoint({"next": (day + timedelta(days=1)).isoformat()})
        return JobOutcome(message=f"{start}～{end}：完成 {done} 個交易日，另有 {closed} 天確認休市")


def _require_stocks(ctx: JobContext) -> None:
    with ctx.engine.connect() as conn:
        if not conn.execute(text("SELECT EXISTS (SELECT 1 FROM stocks)")).scalar_one():
            raise JobError("股票主檔是空的，請先執行 sync_stocks")
