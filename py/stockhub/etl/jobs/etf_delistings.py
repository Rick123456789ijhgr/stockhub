"""Delisted ETFs, derived from the exchanges' own daily quote tables already in RawStore.

Neither exchange publishes a list of terminated ETFs (the company delisting lists leave them
out), and the only third-party list (FinMind) has inconsistent dates. The daily tables are
official and complete, though: an ETF code that is not in today's master list but traded on
earlier days stopped trading after its last day there. So one pass over the stored daily
tables (no network) gives each such ETF's market, name, first and last trading day, and its
bars, which the backfill skipped as unknown codes.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import ClassVar

from sqlalchemy import Connection, text

from stockhub.etl.jobs.base import Job, JobContext, JobError, JobOutcome, register_job
from stockhub.etl.jobs.market_data import (
    DelistingStats,
    apply_delisting,
    refine_estimated_listed_dates,
    store_daily_bars,
)
from stockhub.etl.providers.base import DailyBar, Delisting, Market, PriceProvider, RawResponse

log = logging.getLogger(__name__)

DAILY_DATASETS: dict[str, tuple[str, Market]] = {
    "twse": ("mi_index", "twse"),
    "tpex": ("otc_quotes", "tpex"),
}
"""provider -> (raw dataset of its daily quote table, market)."""
DERIVED_REASON = "derived:last-trade"
"""stocks.delisting_reason of ETFs found this way: the date is the day after the last trade."""


def is_etf_symbol(symbol: str) -> bool:
    """ETF codes: 0050～0099 and 00xxx[x] (00631L, 00679B …).

    0001～0049 were closed-end funds (受益憑證, e.g. 0015 富邦); ETNs (02xxxx) and TDRs
    (91xx) are not ETFs either.
    """
    if not symbol.startswith("00"):
        return False
    if len(symbol) == 4:
        return symbol.isdigit() and int(symbol) >= 50
    return len(symbol) >= 5


@dataclass
class Sighting:
    """Where and when an unknown ETF code appeared in the daily tables."""

    market: Market
    name: str
    first: date
    last: date
    bars: dict[tuple[str, int], list[DailyBar]] = field(default_factory=lambda: defaultdict(list))
    """(provider, raw object id) -> bars, so each bar keeps its raw source."""

    def see(self, bar: DailyBar, market: Market) -> None:
        if bar.trade_date >= self.last:
            self.last, self.market = bar.trade_date, market
            self.name = bar.name or self.name
        self.first = min(self.first, bar.trade_date)


def derive_delistings(
    sightings: dict[str, Sighting],
    latest: dict[Market, date],
    next_trading_day: dict[date, date],
) -> tuple[list[Delisting], list[str]]:
    """Delistings for codes that stopped trading before their market's latest table.

    Returns (delistings, codes still trading but missing from the master list).
    """
    delisted, still_trading = [], []
    for symbol, seen in sorted(sightings.items()):
        if seen.last >= latest[seen.market]:
            still_trading.append(symbol)
            continue
        delisted.append(
            Delisting(
                symbol=symbol,
                name=seen.name,
                market=seen.market,
                delisted_date=next_trading_day[seen.last],
                reason=DERIVED_REASON,
            )
        )
    return delisted, still_trading


def _next_trading_days(conn: Connection, days: set[date]) -> dict[date, date]:
    rows = conn.execute(
        text(
            "SELECT d.day, (SELECT min(c.date) FROM trading_calendar c "
            "  WHERE c.date > d.day AND c.is_trading_day) AS next "
            "FROM unnest(CAST(:days AS date[])) AS d(day)"
        ),
        {"days": sorted(days)},
    ).all()
    return {r.day: r.next for r in rows if r.next is not None}


@register_job
class DeriveDelistedEtfsJob(Job):
    name: ClassVar[str] = "derive_delisted_etfs"
    description: ClassVar[str] = (
        "Find delisted ETFs (and store their bars) in the daily tables already in RawStore; "
        "no network. Run after a history backfill (param dry_run=true only reports)."
    )
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        dry_run = str(ctx.params.get("dry_run", "")).lower() in {"1", "true", "yes"}
        with ctx.engine.connect() as conn:
            backfilling = conn.execute(
                text(
                    "SELECT count(*) FROM job_runs "
                    "WHERE job_name = 'backfill_prices' AND status = 'running'"
                )
            ).scalar_one()
        if backfilling and not dry_run:
            # Mid-backfill the tables stop at the backfill's current date, so ETFs that
            # still trade later would look delisted.
            raise JobError("a backfill_prices run is in progress; rerun after it (or dry_run=true)")
        parsers = {
            p.name: p
            for p in router.registry.providers_for("price")
            if isinstance(p, PriceProvider)
        }
        with ctx.engine.connect() as conn:
            known = {r.symbol for r in conn.execute(text("SELECT DISTINCT symbol FROM stocks"))}
            objects = conn.execute(
                text(
                    "SELECT DISTINCT ON (provider, params->>'date') id, provider, dataset, uri, "
                    "params FROM raw_objects "
                    "WHERE (provider = 'twse' AND dataset = 'mi_index') "
                    "   OR (provider = 'tpex' AND dataset = 'otc_quotes') "
                    "ORDER BY provider, params->>'date', fetched_at DESC"
                )
            ).all()
        sightings: dict[str, Sighting] = {}
        latest: dict[Market, date] = {}
        for index, obj in enumerate(objects):
            provider = parsers.get(obj.provider)
            if provider is None:
                continue
            market = DAILY_DATASETS[obj.provider][1]
            raw = RawResponse(obj.dataset, ctx.rawstore.get(obj.uri), dict(obj.params))
            try:
                bars = provider.parse_daily_prices(raw)
            except Exception as exc:  # one bad table must not stop the scan
                log.warning("skipping %s: %s", obj.uri, exc)
                continue
            if bars:
                latest[market] = max(latest.get(market, bars[0].trade_date), bars[0].trade_date)
            for bar in bars:
                if bar.symbol in known or not is_etf_symbol(bar.symbol):
                    continue
                seen = sightings.get(bar.symbol)
                if seen is None:
                    seen = sightings[bar.symbol] = Sighting(
                        market, bar.name or bar.symbol, bar.trade_date, bar.trade_date
                    )
                seen.see(bar, market)
                seen.bars[(obj.provider, obj.id)].append(bar)
            if index % 500 == 0:
                log.info("scanned %d/%d daily tables", index, len(objects))

        with ctx.engine.begin() as conn:
            next_days = _next_trading_days(conn, {s.last for s in sightings.values()})
            delisted, still_trading = derive_delistings(sightings, latest, next_days)
            if dry_run:
                summary = "、".join(f"{d.symbol} {d.name}（{d.delisted_date}）" for d in delisted)
                return JobOutcome(
                    message=f"試算：掃描 {len(objects)} 份，下市 ETF {len(delisted)} 檔：{summary}"
                )
            stats = DelistingStats()
            for item in delisted:
                apply_delisting(conn, item, stats)
            written = 0
            for item in delisted:
                for (source, raw_id), bars in sightings[item.symbol].bars.items():
                    written += store_daily_bars(conn, bars, source, raw_id).written
            refined = refine_estimated_listed_dates(conn)
        ctx.add_rows(stats.inserted + written)
        if still_trading:
            log.warning("ETF codes trading but not in the master list: %s", still_trading)
        return JobOutcome(
            message=(
                f"掃描日線表 {len(objects)} 份：下市 ETF {len(delisted)} 檔（{stats}），"
                f"寫入日線 {written} 筆，修正上市日 {refined}；"
                f"仍在交易但不在主檔 {len(still_trading)} 檔"
            )
        )
