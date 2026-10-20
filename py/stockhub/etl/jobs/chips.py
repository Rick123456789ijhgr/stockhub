"""Chip jobs (籌碼, M4): institutional trades, margin, foreign holdings, market totals, and
the weekly TDCC shareholding distribution.

Every (dataset, market, date) fetched is recorded in chip_coverage, which drives the
catch-up of sync_chips, the resume of backfill_chips and the /status summary. A table the
exchange has not published yet (margin appears in the evening) is simply left for the next
run; only a past trading day that comes back empty is recorded as covered with 0 rows.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, ClassVar, Literal, Protocol

from sqlalchemy import Connection, text

from stockhub.common.db import upsert
from stockhub.common.timeutil import TAIPEI, taipei_today, utcnow
from stockhub.common.trading_calendar import trading_days_between
from stockhub.etl.jobs.base import Job, JobContext, JobError, JobOutcome, register_job
from stockhub.etl.jobs.market_data import MARKETS, stock_ids_on
from stockhub.etl.providers.base import (
    DistributionLevel,
    ForeignHolding,
    InstitutionalTrade,
    MarginTable,
    Market,
    MarketInstitutional,
)
from stockhub.etl.providers.router import ChipKind, Fetched, ProviderRouter
from stockhub.etl.quality import (
    check_distribution,
    check_foreign_holding,
    check_institutional_trade,
    check_margin_balance,
)

log = logging.getLogger(__name__)

Dataset = Literal["institutional", "margin", "foreign_holdings", "market_institutional"]
CHUNK = 2000
"""Rows per INSERT (PostgreSQL allows 65,535 bind parameters per statement)."""
CATCH_UP_DAYS = 10
"""sync_chips without a date looks back this many trading days for missing tables."""
PUBLISH_TIME = (14, 30)
"""Taipei time before which today's tables are not even tried."""
HISTORY_START = date(2012, 5, 2)
"""First day of TWSE's per-stock institutional table; the default backfill start (D-097)."""


# ----------------------------------------------------------------------------- storing


@dataclass
class StoreStats:
    received: int = 0
    written: int = 0
    quarantined: int = 0
    unknown: int = 0

    def add(self, other: StoreStats) -> None:
        self.received += other.received
        self.written += other.written
        self.quarantined += other.quarantined
        self.unknown += other.unknown

    def __str__(self) -> str:
        text_ = f"收到 {self.received}、寫入 {self.written}"
        if self.quarantined:
            text_ += f"、隔離 {self.quarantined}"
        if self.unknown:
            text_ += f"、非主檔略過 {self.unknown}"
        return text_


def _upsert_chunks(
    conn: Connection, table: str, rows: Sequence[Mapping[str, Any]], keys: Sequence[str]
) -> int:
    """Upsert in chunks; fetched_at is kept from the first insert, so a rerun with the same
    numbers writes nothing."""
    if not rows:
        return 0
    update = [c for c in rows[0] if c not in keys and c != "fetched_at"]
    return sum(
        upsert(conn, table, rows[i : i + CHUNK], keys, update) for i in range(0, len(rows), CHUNK)
    )


def _quarantine(
    conn: Connection,
    dataset: str,
    rows: list[tuple[int, date, list[str], Any]],
    source: str,
    raw_object_id: int | None,
) -> None:
    for stock_id, day, reasons, payload in rows:
        conn.execute(
            text(
                "INSERT INTO chip_quarantine (dataset, stock_id, trade_date, source, payload, "
                "reasons, raw_object_id) VALUES (:dataset, :stock_id, :day, :source, "
                "CAST(:payload AS jsonb), :reasons, :raw) "
                "ON CONFLICT ON CONSTRAINT chip_quarantine_natural_key DO UPDATE SET "
                "payload = excluded.payload, reasons = excluded.reasons, "
                "raw_object_id = excluded.raw_object_id, created_at = now(), "
                "resolved_at = NULL, resolution = NULL"
            ),
            {
                "dataset": dataset,
                "stock_id": stock_id,
                "day": day,
                "source": source,
                "payload": json.dumps(payload),
                "reasons": reasons,
                "raw": raw_object_id,
            },
        )


CHIP_TABLES: dict[str, tuple[str, str]] = {
    "institutional": ("institutional_trades_daily", "trade_date"),
    "margin": ("margin_daily", "trade_date"),
    "foreign_holdings": ("foreign_holdings_daily", "trade_date"),
    "distribution": ("shareholding_distribution", "week_date"),
}
"""Quarantine dataset -> (table, date column)."""


def supersede_quarantine(conn: Connection, dataset: str, day: date, source: str) -> int:
    """Pending quarantine rows of that day whose stock now has a clean row are superseded."""
    table, column = CHIP_TABLES[dataset]
    return conn.execute(
        text(
            f"UPDATE chip_quarantine q SET resolved_at = now(), resolution = 'superseded' "  # noqa: S608 - fixed names
            f"WHERE q.resolved_at IS NULL AND q.dataset = :dataset AND q.trade_date = :day "
            f"AND q.source = :source AND EXISTS (SELECT 1 FROM {table} t "
            f"WHERE t.stock_id = q.stock_id AND t.{column} = q.trade_date)"
        ),
        {"dataset": dataset, "day": day, "source": source},
    ).rowcount


class _PerStock(Protocol):
    symbol: str

    def model_dump(self, *, mode: str = ...) -> dict[str, Any]: ...


def _store_per_stock[T: _PerStock](
    conn: Connection,
    dataset: str,
    items: Sequence[T],
    day: date,
    source: str,
    raw_object_id: int | None,
    check: Callable[[T], list[str]],
    to_row: Callable[[T], dict[str, Any]],
) -> StoreStats:
    """Shared path of the per-stock daily tables: map symbols, check, upsert or quarantine."""
    table, _ = CHIP_TABLES[dataset]
    stats = StoreStats(received=len(items))
    ids = stock_ids_on(conn, day)
    good: dict[int, dict[str, Any]] = {}
    bad = []
    for item in items:
        stock_id = ids.get(item.symbol)
        if stock_id is None:
            stats.unknown += 1
            continue
        reasons = check(item)
        if reasons:
            bad.append((stock_id, day, reasons, item.model_dump(mode="json")))
        else:
            # A reused symbol never appears twice in one day's table; last one wins.
            good[stock_id] = {
                "stock_id": stock_id,
                "trade_date": day,
                **to_row(item),
                "source": source,
            }
    stats.written = _upsert_chunks(conn, table, list(good.values()), ["stock_id", "trade_date"])
    _quarantine(conn, dataset, bad, source, raw_object_id)
    stats.quarantined = len(bad)
    supersede_quarantine(conn, dataset, day, source)
    return stats


INSTITUTIONAL_COLUMNS = [
    "foreign_buy",
    "foreign_sell",
    "foreign_net",
    "foreign_dealer_buy",
    "foreign_dealer_sell",
    "foreign_dealer_net",
    "trust_buy",
    "trust_sell",
    "trust_net",
    "dealer_buy",
    "dealer_sell",
    "dealer_net",
    "dealer_self_net",
    "dealer_hedge_net",
    "total_net",
]
MARGIN_COLUMNS = [
    "margin_buy",
    "margin_sell",
    "margin_redeem",
    "margin_balance",
    "margin_limit",
    "short_sell",
    "short_cover",
    "short_redeem",
    "short_balance",
    "short_limit",
    "offset_shares",
    "note",
]


def store_institutional(
    conn: Connection, fetched: Fetched[InstitutionalTrade], day: date
) -> StoreStats:
    return _store_per_stock(
        conn,
        "institutional",
        fetched.items,
        day,
        fetched.provider,
        fetched.raw.id,
        check_institutional_trade,
        lambda t: {c: getattr(t, c) for c in INSTITUTIONAL_COLUMNS},
    )


def store_margin(conn: Connection, fetched: Fetched[MarginTable], day: date) -> StoreStats:
    stats = StoreStats()
    for table in fetched.items:
        stats.add(
            _store_per_stock(
                conn,
                "margin",
                table.rows,
                day,
                fetched.provider,
                fetched.raw.id,
                check_margin_balance,
                lambda m: {c: getattr(m, c) for c in MARGIN_COLUMNS},
            )
        )
        if table.total is not None:
            total = table.total.model_dump()
            _upsert_chunks(
                conn,
                "market_margin_daily",
                [{**total, "source": fetched.provider}],
                ["market", "trade_date"],
            )
    return stats


def store_foreign_holdings(
    conn: Connection, fetched: Fetched[ForeignHolding], day: date
) -> StoreStats:
    return _store_per_stock(
        conn,
        "foreign_holdings",
        fetched.items,
        day,
        fetched.provider,
        fetched.raw.id,
        check_foreign_holding,
        lambda h: {
            "issued_shares": h.issued_shares,
            "foreign_shares": h.foreign_shares,
            "foreign_ratio": h.foreign_ratio,
            "limit_ratio": h.limit_ratio,
        },
    )


def store_market_institutional(
    conn: Connection, fetched: Fetched[MarketInstitutional], day: date
) -> StoreStats:
    rows = [{**r.model_dump(), "source": fetched.provider} for r in fetched.items]
    written = _upsert_chunks(
        conn, "market_institutional_daily", rows, ["market", "trade_date", "investor"]
    )
    return StoreStats(received=len(rows), written=written)


def record_coverage(
    conn: Connection, dataset: str, market: str, day: date, rows: int, source: str
) -> None:
    conn.execute(
        text(
            "INSERT INTO chip_coverage (dataset, market, trade_date, rows, source) "
            "VALUES (:dataset, :market, :day, :rows, :source) "
            "ON CONFLICT (dataset, market, trade_date) DO UPDATE SET rows = excluded.rows, "
            "source = excluded.source, fetched_at = now()"
        ),
        {"dataset": dataset, "market": market, "day": day, "rows": rows, "source": source},
    )


# ----------------------------------------------------------------------------- one day


@dataclass(frozen=True)
class ChipDataset:
    name: Dataset
    kind: ChipKind
    label: str
    fetch: Callable[[ProviderRouter, date, Market], Fetched[Any]]
    store: Callable[[Connection, Fetched[Any], date], StoreStats]
    count: Callable[[Fetched[Any]], int] = lambda f: len(f.items)


DATASETS: tuple[ChipDataset, ...] = (
    ChipDataset(
        "institutional",
        "institutional_trades",
        "三大法人",
        lambda r, d, m: r.institutional_trades(d, m),
        store_institutional,
    ),
    ChipDataset(
        "margin",
        "margin",
        "融資融券",
        lambda r, d, m: r.margin(d, m),
        store_margin,
        lambda f: sum(len(t.rows) for t in f.items),
    ),
    ChipDataset(
        "foreign_holdings",
        "foreign_holdings",
        "外資持股",
        lambda r, d, m: r.foreign_holdings(d, m),
        store_foreign_holdings,
    ),
    ChipDataset(
        "market_institutional",
        "market_institutional",
        "法人金額",
        lambda r, d, m: r.market_institutional(d, m),
        store_market_institutional,
    ),
)
DATASET_NAMES = [d.name for d in DATASETS]


def covered(conn: Connection, start: date, end: date) -> set[tuple[str, str, date]]:
    rows = conn.execute(
        text(
            "SELECT dataset, market, trade_date FROM chip_coverage "
            "WHERE trade_date BETWEEN :start AND :end"
        ),
        {"start": start, "end": end},
    ).all()
    return {(r.dataset, r.market, r.trade_date) for r in rows}


@dataclass
class DayReport:
    stored: dict[Dataset, StoreStats] = field(default_factory=lambda: defaultdict(StoreStats))
    pending: list[str] = field(default_factory=list)
    """Tables not published yet (left for the next run)."""
    empty: list[str] = field(default_factory=list)
    """Past trading days the exchange published empty (recorded as covered)."""
    requests: int = 0

    def summary(self) -> str:
        labels = {d.name: d.label for d in DATASETS}
        parts = [f"{labels[name]} {stats}" for name, stats in self.stored.items()]
        if self.empty:
            parts.append(f"交易所無資料 {len(self.empty)} 份（{'、'.join(self.empty[:5])}）")
        if self.pending:
            parts.append(f"尚未公布 {len(self.pending)} 份（{'、'.join(self.pending[:5])}）")
        return "；".join(parts) or "沒有需要抓的資料"


def ingest_chip_day(
    ctx: JobContext,
    day: date,
    report: DayReport,
    datasets: Sequence[ChipDataset] = DATASETS,
    skip: set[tuple[str, str, date]] | None = None,
) -> None:
    """Fetch and store every requested table of one trading day, both markets interleaved
    (TWSE and TPEx have separate rate limits). Tables in `skip` are already covered."""
    router = ctx.require_router()
    today = taipei_today()
    for dataset in datasets:
        for market in MARKETS:
            since = router.chip_since(dataset.kind, market)
            if since is None or day < since:
                continue
            if skip is not None and (dataset.name, market, day) in skip:
                continue
            fetched = dataset.fetch(router, day, market)
            report.requests += 1
            published = dataset.count(fetched)
            tag = f"{dataset.label} {market} {day}"
            with ctx.engine.begin() as conn:
                if published == 0:
                    if day >= today:
                        report.pending.append(tag)
                        continue
                    report.empty.append(tag)
                else:
                    stats = dataset.store(conn, fetched, day)
                    report.stored[dataset.name].add(stats)
                    ctx.add_rows(stats.written)
                record_coverage(conn, dataset.name, market, day, published, fetched.provider)


def pick_datasets(value: object) -> list[ChipDataset]:
    """`datasets=margin,institutional` limits a run; empty means all."""
    if not value:
        return list(DATASETS)
    names = {n.strip() for n in str(value).split(",") if n.strip()}
    unknown = names - set(DATASET_NAMES)
    if unknown:
        raise JobError(f"未知的資料集 {sorted(unknown)}；可用：{', '.join(DATASET_NAMES)}")
    return [d for d in DATASETS if d.name in names]


def _require_stocks(conn: Connection) -> None:
    if not conn.execute(text("SELECT EXISTS (SELECT 1 FROM stocks)")).scalar_one():
        raise JobError("股票主檔是空的，請先執行 sync_stocks")


# ----------------------------------------------------------------------------- jobs


@register_job
class SyncChipsJob(Job):
    name: ClassVar[str] = "sync_chips"
    description: ClassVar[str] = (
        "Institutional trades, margin, foreign holdings and market totals: --param date= "
        "re-fetches that day; without it, every table missing in the last 10 trading days"
    )
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        datasets = pick_datasets(ctx.params.get("datasets"))
        report = DayReport()
        with ctx.engine.connect() as conn:
            _require_stocks(conn)
        if ctx.params.get("date"):
            day = date.fromisoformat(str(ctx.params["date"]))
            ingest_chip_day(ctx, day, report, datasets)
            return JobOutcome(message=f"{day}：{report.summary()}")
        today = taipei_today()
        now = utcnow().astimezone(TAIPEI)
        with ctx.engine.connect() as conn:
            days = trading_days_between(conn, today - timedelta(days=CATCH_UP_DAYS * 2), today)
            if days and days[-1] == today and (now.hour, now.minute) < PUBLISH_TIME:
                days = days[:-1]
            days = days[-CATCH_UP_DAYS:]
            done = covered(conn, days[0], days[-1]) if days else set()
        for day in days:
            ingest_chip_day(ctx, day, report, datasets, skip=done)
        if report.requests == 0:
            return JobOutcome("skipped", f"近 {len(days)} 個交易日的籌碼都已抓齊")
        return JobOutcome(message=f"{days[0]}～{days[-1]}：{report.summary()}")


@register_job
class BackfillChipsJob(Job):
    name: ClassVar[str] = "backfill_chips"
    description: ClassVar[str] = (
        "Chip tables for every trading day in [start, end] (default 2012-05-02 to today; "
        "skips covered tables; resumable; datasets=margin,... limits it)"
    )
    uses_date: ClassVar[bool] = False
    timeout: ClassVar[timedelta] = timedelta(hours=36)

    def run(self, ctx: JobContext) -> JobOutcome:
        datasets = pick_datasets(ctx.params.get("datasets"))
        end = date.fromisoformat(ctx.params.get("end") or taipei_today().isoformat())
        start = date.fromisoformat(ctx.params.get("start") or HISTORY_START.isoformat())
        with ctx.engine.connect() as conn:
            _require_stocks(conn)
            all_days = trading_days_between(conn, start, end)
            done = covered(conn, start, end)
        resume = (ctx.checkpoint or {}).get("next")
        days = [d for d in all_days if resume is None or d >= date.fromisoformat(resume)]
        report = DayReport()
        finished = len(all_days) - len(days)
        for day in days:
            ingest_chip_day(ctx, day, report, datasets, skip=done)
            finished += 1
            ctx.save_checkpoint(
                {
                    "next": (day + timedelta(days=1)).isoformat(),
                    "done": finished,
                    "total": len(all_days),
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                }
            )
            if finished % 20 == 0:
                log.info(
                    "backfill_chips %s (%d/%d) %s", day, finished, len(all_days), report.summary()
                )
        return JobOutcome(
            message=f"{start}～{end}：{len(all_days)} 個交易日，請求 {report.requests} 次；"
            f"{report.summary()}"
        )


def store_distribution(
    conn: Connection, levels: Sequence[DistributionLevel], source: str, raw_object_id: int | None
) -> tuple[date, StoreStats]:
    """One TDCC week; a stock whose brackets do not add up is quarantined as a whole."""
    if not levels:
        raise JobError("集保股權分散表是空的")
    week = levels[0].week_date
    if any(lv.week_date != week for lv in levels):
        raise JobError("集保股權分散表含有多個資料日期")
    stats = StoreStats(received=len(levels))
    ids = stock_ids_on(conn, week)
    by_symbol: dict[str, list[DistributionLevel]] = defaultdict(list)
    for lv in levels:
        by_symbol[lv.symbol].append(lv)
    good: list[dict[str, Any]] = []
    bad = []
    for symbol, rows in by_symbol.items():
        stock_id = ids.get(symbol)
        if stock_id is None:
            stats.unknown += len(rows)
            continue
        reasons = check_distribution(rows)
        if reasons:
            bad.append((stock_id, week, reasons, [r.model_dump(mode="json") for r in rows]))
            continue
        good.extend(
            {
                "stock_id": stock_id,
                "week_date": week,
                "level": r.level,
                "holders": r.holders,
                "shares": r.shares,
                "ratio": r.ratio,
                "source": source,
            }
            for r in rows
        )
    stats.written = _upsert_chunks(
        conn, "shareholding_distribution", good, ["stock_id", "week_date", "level"]
    )
    _quarantine(conn, "distribution", bad, source, raw_object_id)
    stats.quarantined = len(bad)
    supersede_quarantine(conn, "distribution", week, source)
    return week, stats


@register_job
class SyncShareholdingDistributionJob(Job):
    name: ClassVar[str] = "sync_shareholding_distribution"
    description: ClassVar[str] = (
        "TDCC weekly shareholding distribution (latest week only; stored once per week)"
    )
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        fetched = router.shareholding_distribution()
        week = fetched.items[0].week_date if fetched.items else None
        with ctx.engine.begin() as conn:
            _require_stocks(conn)
            if week is not None and not ctx.params.get("force"):
                seen = conn.execute(
                    text(
                        "SELECT 1 FROM chip_coverage WHERE dataset = 'distribution' "
                        "AND market = 'all' AND trade_date = :w"
                    ),
                    {"w": week},
                ).first()
                if seen is not None:
                    return JobOutcome("skipped", f"{week} 這一週已經存過")
            week, stats = store_distribution(conn, fetched.items, fetched.provider, fetched.raw.id)
            record_coverage(conn, "distribution", "all", week, len(fetched.items), fetched.provider)
        ctx.add_rows(stats.written)
        return JobOutcome(message=f"集保 {week}：{stats}")
