"""Market and macro series jobs (M5): Taiwan indices, international markets, US rates and
macro data, the NDC business indicators, and the macro alerts.

What to fetch comes from the market_series catalog; which source serves a series is the
router's business (PROVIDERS_MARKET_SERIES order, D-105). Sources that answer one month per
request (the exchanges' index tables) are asked month by month. A failed series does not
stop the others: the job stores what it got and fails at the end, so the failure is
notified and the next run catches up from the last stored date.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import Connection, func, literal_column, or_, text
from sqlalchemy.dialects.postgresql import insert

from stockhub.common.db import get_table
from stockhub.common.notifier import Notifier
from stockhub.common.timeutil import taipei_today, utcnow
from stockhub.engine.macro import Change, Point, light_change, rate_change
from stockhub.etl.jobs.base import Job, JobContext, JobError, JobOutcome, register_job
from stockhub.etl.providers.base import ProviderError, SeriesObservation
from stockhub.etl.providers.router import ProviderRouter
from stockhub.etl.quality import check_series_observation

log = logging.getLogger(__name__)

CHUNK = 2000
"""Rows per INSERT."""
DAILY_LOOKBACK = timedelta(days=10)
"""sync_markets re-asks this far behind the last stored date (late or revised closes)."""
DAILY_FIRST_FETCH = timedelta(days=30)
"""A daily series with nothing stored yet starts this far back (backfill_markets does history)."""
MONTHLY_LOOKBACK = timedelta(days=400)
"""Monthly macro series are revised for months; sync_macro re-reads a year of them."""
ALERT_FRESH = timedelta(days=3)
"""Macro alerts only fire for observations written this recently (not for old history)."""
VALUE_COLUMNS = ("open", "high", "low", "value", "label", "source")
NO_OHLC = {"open": None, "high": None, "low": None}


@dataclass(frozen=True)
class SeriesMeta:
    code: str
    name: str
    frequency: str
    has_ohlc: bool
    positive: bool
    max_daily_move: Decimal | None
    history_start: date


def load_series(conn: Connection, codes: Sequence[str] | None = None) -> list[SeriesMeta]:
    """Enabled catalog rows in display order (all enabled ones when codes is None)."""
    rows = conn.execute(
        text(
            "SELECT code, name, frequency, has_ohlc, positive, max_daily_move, history_start "
            "FROM market_series WHERE enabled ORDER BY sort_order"
        )
    ).all()
    metas = [SeriesMeta(*r) for r in rows]
    if codes is None:
        return metas
    unknown = set(codes) - {m.code for m in metas}
    if unknown:
        raise JobError(f"未知或停用的序列 {sorted(unknown)}")
    return [m for m in metas if m.code in codes]


def pick_codes(value: object) -> list[str] | None:
    """`series=SPX,SOX` limits a run; empty means every series of the job."""
    if not value:
        return None
    return [c.strip().upper() for c in str(value).split(",") if c.strip()]


def pending_quarantine(conn: Connection) -> dict[str, date]:
    """Earliest observation awaiting review per series: catch-up re-asks from there, so a
    source that corrected itself supersedes the quarantined value."""
    return {
        r.series_code: r.first
        for r in conn.execute(
            text(
                "SELECT series_code, min(obs_date) AS first FROM market_series_quarantine "
                "WHERE resolved_at IS NULL GROUP BY series_code"
            )
        )
    }


def last_dates(conn: Connection) -> dict[str, date]:
    return {
        r.code: r.last_date
        for r in conn.execute(
            text("SELECT code, last_date FROM market_series_status WHERE last_date IS NOT NULL")
        )
    }


# ----------------------------------------------------------------------------- storing


@dataclass
class StoreStats:
    received: int = 0
    written: int = 0
    quarantined: int = 0

    def add(self, other: StoreStats) -> None:
        self.received += other.received
        self.written += other.written
        self.quarantined += other.quarantined


def _write_values(conn: Connection, rows: list[dict[str, Any]]) -> int:
    """Upsert observations; a row whose numbers, label and source are unchanged is left alone
    (fetched_at then still says when it last changed)."""
    if not rows:
        return 0
    table = get_table(conn, "market_series_values")
    written = 0
    for i in range(0, len(rows), CHUNK):
        stmt = insert(table).values(rows[i : i + CHUNK])
        stmt = stmt.on_conflict_do_update(
            index_elements=["series_code", "obs_date"],
            set_={c: stmt.excluded[c] for c in (*VALUE_COLUMNS, "raw_object_id")}
            | {"fetched_at": func.now()},
            where=or_(*(table.c[c].is_distinct_from(stmt.excluded[c]) for c in VALUE_COLUMNS)),
        )
        written += len(conn.execute(stmt.returning(literal_column("1"))).all())
    return written


def _previous_value(conn: Connection, code: str, before: date) -> Decimal | None:
    value: Decimal | None = conn.execute(
        text(
            "SELECT value FROM market_series_values WHERE series_code = :code "
            "AND obs_date < :before ORDER BY obs_date DESC LIMIT 1"
        ),
        {"code": code, "before": before},
    ).scalar_one_or_none()
    return value


def store_observations(
    conn: Connection,
    meta: SeriesMeta,
    items: Sequence[SeriesObservation],
    source: str,
    raw_object_id: int | None,
) -> StoreStats:
    """Check and upsert one series' observations; failures go to market_series_quarantine
    and pending quarantine rows of dates that now have a clean value are superseded.

    Series without has_ohlc keep only the value: for futures and FX, Yahoo's close is the
    settlement or a fixing outside the session its high and low cover (D-107)."""
    by_date = {
        o.obs_date: o if meta.has_ohlc else o.model_copy(update=NO_OHLC)
        for o in items
        if o.code == meta.code
    }
    stats = StoreStats(received=len(by_date))
    if not by_date:
        return stats
    days = sorted(by_date)
    previous = _previous_value(conn, meta.code, days[0])
    good: list[dict[str, Any]] = []
    for day in days:
        obs = by_date[day]
        reasons = check_series_observation(
            obs, previous, positive=meta.positive, max_move=meta.max_daily_move
        )
        if reasons:
            stats.quarantined += 1
            conn.execute(
                text(
                    "INSERT INTO market_series_quarantine (series_code, obs_date, source, "
                    "payload, reasons, raw_object_id) VALUES (:code, :day, :source, "
                    "CAST(:payload AS jsonb), :reasons, :raw) "
                    "ON CONFLICT ON CONSTRAINT market_series_quarantine_natural_key DO UPDATE "
                    "SET payload = excluded.payload, reasons = excluded.reasons, "
                    "raw_object_id = excluded.raw_object_id, created_at = now(), "
                    "resolved_at = NULL, resolution = NULL"
                ),
                {
                    "code": meta.code,
                    "day": day,
                    "source": source,
                    "payload": json.dumps(obs.model_dump(mode="json")),
                    "reasons": reasons,
                    "raw": raw_object_id,
                },
            )
            continue
        previous = obs.value
        good.append(
            {
                "series_code": meta.code,
                "obs_date": day,
                "open": obs.open,
                "high": obs.high,
                "low": obs.low,
                "value": obs.value,
                "label": obs.label,
                "source": source,
                "raw_object_id": raw_object_id,
            }
        )
    stats.written = _write_values(conn, good)
    if good:
        conn.execute(
            text(
                "UPDATE market_series_quarantine q SET resolved_at = now(), "
                "resolution = 'superseded' WHERE q.resolved_at IS NULL "
                "AND q.series_code = :code AND q.obs_date = ANY(:days) AND EXISTS ("
                "SELECT 1 FROM market_series_values v WHERE v.series_code = q.series_code "
                "AND v.obs_date = q.obs_date)"
            ),
            {"code": meta.code, "days": [r["obs_date"] for r in good]},
        )
    return stats


# ----------------------------------------------------------------------------- fetching


def month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """[start, end] split at month boundaries."""
    chunks = []
    cursor = start
    while cursor <= end:
        next_month = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
        chunks.append((cursor, min(end, next_month - timedelta(days=1))))
        cursor = next_month
    return chunks


@dataclass
class SeriesReport:
    stats: dict[str, StoreStats] = field(default_factory=lambda: defaultdict(StoreStats))
    sources: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    failures: list[str] = field(default_factory=list)
    requests: int = 0

    def summary(self) -> str:
        parts = []
        for code, stats in self.stats.items():
            text_ = f"{code} {stats.written}/{stats.received}"
            if stats.quarantined:
                text_ += f"（隔離 {stats.quarantined}）"
            sources = self.sources.get(code)
            if sources:
                text_ += f" [{','.join(sorted(sources))}]"
            parts.append(text_)
        out = f"請求 {self.requests} 次；" + ("、".join(parts) or "沒有資料")
        if self.failures:
            out += f"；失敗 {len(self.failures)}：" + "；".join(self.failures)
        return out


def fetch_range(
    ctx: JobContext,
    router: ProviderRouter,
    meta: SeriesMeta,
    ranges: Sequence[tuple[date, date]],
    report: SeriesReport,
) -> None:
    for start, end in ranges:
        fetched = router.market_series(meta.code, start, end)
        report.requests += 1
        with ctx.engine.begin() as conn:
            stats = store_observations(conn, meta, fetched.items, fetched.provider, fetched.raw.id)
        report.stats[meta.code].add(stats)
        if fetched.items:
            report.sources[meta.code].add(fetched.provider)
        ctx.add_rows(stats.written)


def series_ranges(
    router: ProviderRouter, code: str, start: date, end: date
) -> list[tuple[date, date]]:
    if start > end:
        return []
    return month_chunks(start, end) if router.series_monthly(code) else [(start, end)]


def catch_up(
    ctx: JobContext,
    metas: Sequence[SeriesMeta],
    lookback: timedelta,
    first_fetch: timedelta | None,
    report: SeriesReport,
) -> None:
    """Fetch each series from a little before its last stored date to today. A series with
    nothing stored starts `first_fetch` ago (None = from its history_start)."""
    router = ctx.require_router()
    today = taipei_today()
    with ctx.engine.connect() as conn:
        latest = last_dates(conn)
        pending = pending_quarantine(conn)
    for meta in metas:
        if not router.series_providers(meta.code):
            continue
        last = latest.get(meta.code)
        if last is not None:
            start = last - lookback
        elif first_fetch is not None:
            start = today - first_fetch
        else:
            start = meta.history_start
        if meta.code in pending:
            start = min(start, pending[meta.code])
        start = max(start, meta.history_start)
        try:
            fetch_range(ctx, router, meta, series_ranges(router, meta.code, start, today), report)
        except ProviderError as exc:
            log.warning("series %s failed: %s", meta.code, exc)
            report.failures.append(f"{meta.code}: {exc}")


def _finish(report: SeriesReport, label: str) -> JobOutcome:
    if report.failures:
        raise JobError(f"{label}：{report.summary()}")
    return JobOutcome(message=f"{label}：{report.summary()}")


@register_job
class SyncMarketsJob(Job):
    name: ClassVar[str] = "sync_markets"
    description: ClassVar[str] = (
        "Daily market series (TW indices, international indices, FX, rates, commodities) from "
        "10 days before the last stored date to today; series=SPX,... limits it"
    )
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        with ctx.engine.connect() as conn:
            metas = load_series(conn, pick_codes(ctx.params.get("series")))
        daily = [m for m in metas if m.frequency == "daily"]
        report = SeriesReport()
        catch_up(ctx, daily, DAILY_LOOKBACK, DAILY_FIRST_FETCH, report)
        return _finish(report, "市場序列")


@register_job
class BackfillMarketsJob(Job):
    name: ClassVar[str] = "backfill_markets"
    description: ClassVar[str] = (
        "History of every market series served by PROVIDERS_MARKET_SERIES from its "
        "history_start (or start=) to end= (default today); resumable; series=SPX,... limits it"
    )
    uses_date: ClassVar[bool] = False
    timeout: ClassVar[timedelta] = timedelta(hours=6)

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        end = date.fromisoformat(ctx.params.get("end") or taipei_today().isoformat())
        start_param = ctx.params.get("start")
        with ctx.engine.connect() as conn:
            metas = load_series(conn, pick_codes(ctx.params.get("series")))
        checkpoint = dict(ctx.checkpoint or {})
        done: list[str] = list(checkpoint.get("done", []))
        report = SeriesReport()
        for meta in metas:
            if meta.code in done or not router.series_providers(meta.code):
                continue
            start = max(meta.history_start, date.fromisoformat(start_param or "1900-01-01"))
            if checkpoint.get("code") == meta.code and checkpoint.get("next"):
                start = max(start, date.fromisoformat(checkpoint["next"]))
            try:
                for chunk in series_ranges(router, meta.code, start, end):
                    fetch_range(ctx, router, meta, [chunk], report)
                    next_day = (chunk[1] + timedelta(days=1)).isoformat()
                    ctx.save_checkpoint({"done": done, "code": meta.code, "next": next_day})
            except ProviderError as exc:
                log.warning("backfill of %s failed: %s", meta.code, exc)
                report.failures.append(f"{meta.code}: {exc}")
                continue
            done.append(meta.code)
            ctx.save_checkpoint({"done": done})
            log.info("backfill_markets %s done: %s", meta.code, report.stats[meta.code])
        return _finish(report, f"市場序列歷史（至 {end}）")


# ----------------------------------------------------------------------------- macro


def record_signal_release(conn: Connection, previous_last: date | None, today: date) -> bool:
    """When a new month of the NDC signal appeared, note the release in macro_events."""
    row = conn.execute(
        text(
            "SELECT obs_date, value, label FROM market_series_values "
            "WHERE series_code = 'TW_SIGNAL' ORDER BY obs_date DESC LIMIT 1"
        )
    ).first()
    if row is None or previous_last is None or row.obs_date <= previous_last:
        return False
    title = (
        f"景氣燈號 {row.obs_date.year} 年 {row.obs_date.month} 月：{row.label} {_num(row.value)} 分"
    )
    conn.execute(
        text(
            "INSERT INTO macro_events (event_date, kind, title, source) "
            "VALUES (:day, 'ndc_signal', :title, 'auto') "
            "ON CONFLICT ON CONSTRAINT macro_events_natural_key DO NOTHING"
        ),
        {"day": today, "title": title},
    )
    return True


@register_job
class SyncMacroJob(Job):
    name: ClassVar[str] = "sync_macro"
    description: ClassVar[str] = (
        "NDC business indicators and light (whole revised history), monthly US macro series "
        "(a year back, revisions), and a macro_events entry when a new signal month appears"
    )
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        report = SeriesReport()
        with ctx.engine.connect() as conn:
            metas = {m.code: m for m in load_series(conn)}
            previous_last = last_dates(conn).get("TW_SIGNAL")
        released = False
        try:
            fetched = router.macro_release()
            report.requests += 1
            with ctx.engine.begin() as conn:
                for code in sorted({o.code for o in fetched.items}):
                    if code not in metas:
                        continue
                    stats = store_observations(
                        conn, metas[code], fetched.items, fetched.provider, fetched.raw.id
                    )
                    report.stats[code].add(stats)
                    report.sources[code].add(fetched.provider)
                    ctx.add_rows(stats.written)
                released = record_signal_release(conn, previous_last, taipei_today())
        except ProviderError as exc:
            report.failures.append(f"景氣指標: {exc}")
        monthly = [m for m in metas.values() if m.frequency == "monthly"]
        catch_up(ctx, monthly, MONTHLY_LOOKBACK, None, report)
        label = "總經" + ("（景氣燈號有新月份）" if released else "")
        return _finish(report, label)


def _points(conn: Connection, code: str, count: int = 2) -> tuple[list[Point], Any]:
    rows = conn.execute(
        text(
            "SELECT obs_date, value, label, fetched_at FROM market_series_values "
            "WHERE series_code = :code ORDER BY obs_date DESC LIMIT :n"
        ),
        {"code": code, "n": count},
    ).all()
    return [Point(r.obs_date, r.value, r.label) for r in reversed(rows)], (
        rows[0].fetched_at if rows else None
    )


def _num(value: Decimal) -> str:
    """41.000000 -> 41, 4.250000 -> 4.25 (numeric columns come back with their scale)."""
    return f"{value.normalize():f}"


def _as_json(point: Point) -> dict[str, str | None]:
    return {"date": point.obs_date.isoformat(), "value": _num(point.value), "label": point.label}


def _signal_title(change: Change) -> str:
    month = change.after.obs_date
    trend = "轉熱" if change.rising else "轉冷"
    return (
        f"景氣燈號{trend}：{change.before.label} → {change.after.label}"
        f"（{month.year} 年 {month.month} 月，{_num(change.after.value)} 分）"
    )


def _rate_title(change: Change) -> str:
    move = "調升" if change.rising else "調降"
    return f"Fed 利率{move}：目標上限 {_num(change.before.value)}% → {_num(change.after.value)}%"


MACRO_RULES = (
    ("business_signal", "TW_SIGNAL", light_change, _signal_title),
    ("policy_rate", "FED_UPPER", rate_change, _rate_title),
)


def check_macro_alerts(conn: Connection, notifier: Notifier) -> int:
    """Alert once per change of the light or the Fed target; returns new alerts."""
    raised = 0
    fresh_after = utcnow() - ALERT_FRESH
    for kind, code, rule, title_of in MACRO_RULES:
        points, fetched_at = _points(conn, code)
        change = rule(points)
        if change is None or fetched_at is None or fetched_at < fresh_after:
            continue
        title = title_of(change)
        detail = {
            "series": code,
            "before": _as_json(change.before),
            "after": _as_json(change.after),
        }
        row = conn.execute(
            text(
                "INSERT INTO alerts (kind, stock_id, trade_date, severity, title, detail) "
                "VALUES (:kind, NULL, :day, 'warning', :title, CAST(:detail AS jsonb)) "
                "ON CONFLICT ON CONSTRAINT alerts_once_per_day DO NOTHING RETURNING id"
            ),
            {"kind": kind, "day": change.obs_date, "title": title, "detail": json.dumps(detail)},
        ).first()
        if row is None:
            continue
        raised += 1
        try:
            notifier.send(
                f"[總經警示] {title}", f"{title}\n請到 /market?tab=macro 查看。", "warning"
            )
        except Exception:  # a broken notifier must not lose the recorded alert
            log.exception("could not send alert %s", row.id)
            continue
        conn.execute(
            text("UPDATE alerts SET notified_at = :now WHERE id = :id"),
            {"now": utcnow(), "id": row.id},
        )
    return raised


@register_job
class CheckMacroAlertsJob(Job):
    name: ClassVar[str] = "check_macro_alerts"
    description: ClassVar[str] = "Alert when the NDC light changes colour or the Fed target moves"
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        with ctx.engine.begin() as conn:
            raised = check_macro_alerts(conn, ctx.notifier)
        ctx.add_rows(raised)
        return JobOutcome(message=f"新增 {raised} 則總經警示")
