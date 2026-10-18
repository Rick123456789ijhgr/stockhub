"""Corporate actions (除權息、減資、面額變更、ETF 分割) and the adj_factor they produce.

sync_corporate_actions  imports the exchanges' event tables (with reference prices);
sync_dividend_details   fills the cash / stock / rights parts of TWSE 權息 events, which the
                        event table publishes only as a total since 2009;
compute_adj_factors     rewrites prices_daily.adj_factor from them and flags price gaps that
                        no recorded event explains (e.g. TPEx par-value changes, reductions
                        before 2011/2013), so they get reviewed instead of silently
                        distorting returns.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import Connection, bindparam, text

from stockhub.common.db import upsert
from stockhub.common.timeutil import taipei_today, utcnow
from stockhub.engine.adjustments import factor_segments, guess_share_ratio
from stockhub.etl.jobs.base import Job, JobContext, JobOutcome, register_job
from stockhub.etl.jobs.market_data import MARKETS, stock_ids_on
from stockhub.etl.providers.base import ActionDataset, CorporateAction, DividendDetail
from stockhub.etl.quality import check_corporate_action

log = logging.getLogger(__name__)

DATASETS: tuple[ActionDataset, ...] = (
    "dividend",
    "capital_reduction",
    "par_value_change",
    "etf_split",
)
ACTION_COLUMNS = ["cash_dividend", "stock_dividend_ratio", "ratio", "prev_close", "reference_price"]
PART_COLUMNS = frozenset({"cash_dividend", "stock_dividend_ratio"})
"""Event parts some tables leave out (TWSE 權息 since 2009); sync_dividend_details fills them."""
MANUAL_SOURCE = "manual"
"""Events confirmed by hand on /admin (from a price-gap guess); an imported event on the same
stock and day replaces them."""
DEFAULT_LOOKBACK = timedelta(days=30)


# ----------------------------------------------------------------------------- import


@dataclass
class ActionStats:
    written: int = 0
    quarantined: int = 0
    unknown: int = 0
    received: int = 0

    def add(self, other: ActionStats) -> None:
        self.written += other.written
        self.quarantined += other.quarantined
        self.unknown += other.unknown
        self.received += other.received

    def __str__(self) -> str:
        return (
            f"收到 {self.received}、寫入 {self.written}、隔離 {self.quarantined}、"
            f"非主檔代號略過 {self.unknown}"
        )


def store_corporate_actions(
    conn: Connection, actions: list[CorporateAction], source: str, raw_object_id: int | None
) -> ActionStats:
    """Clean events go to corporate_actions, failing ones to the quarantine table."""
    stats = ActionStats(received=len(actions))
    ids = {day: stock_ids_on(conn, day) for day in {a.ex_date for a in actions}}
    good: dict[tuple[int, date, str], dict[str, Any]] = {}
    for action in actions:
        stock_id = ids[action.ex_date].get(action.symbol)
        if stock_id is None:
            stats.unknown += 1
            continue
        reasons = check_corporate_action(action)
        if reasons:
            _quarantine(conn, action, stock_id, reasons, source, raw_object_id)
            stats.quarantined += 1
            continue
        good[(stock_id, action.ex_date, action.action_type)] = {
            "stock_id": stock_id,
            "ex_date": action.ex_date,
            "action_type": action.action_type,
            **{column: getattr(action, column) for column in ACTION_COLUMNS},
            "source": source,
            "raw_object_id": raw_object_id,
        }
    # source/raw_object_id keep the first sighting, so re-fetching a (grown) table that
    # repeats an unchanged event writes nothing. A part the table leaves out (NULL) never
    # overwrites one filled in later from the event's detail page.
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in good.values():
        columns = tuple(c for c in ACTION_COLUMNS if c not in PART_COLUMNS or row[c] is not None)
        groups[columns].append(row)
    stats.written = sum(
        upsert(conn, "corporate_actions", rows, ["stock_id", "ex_date", "action_type"], columns)
        for columns, rows in groups.items()
    )
    if good:
        keys = json.dumps([{"stock_id": s, "ex_date": d.isoformat()} for s, d, _ in good])
        # An official event replaces a hand-confirmed guess for the same day, so the day is
        # not adjusted twice (the guess may carry a different action_type).
        conn.execute(
            text(
                "DELETE FROM corporate_actions m USING jsonb_to_recordset(CAST(:keys AS jsonb)) "
                "  AS k(stock_id bigint, ex_date date) "
                "WHERE m.source = :manual AND m.stock_id = k.stock_id AND m.ex_date = k.ex_date"
            ),
            {"keys": keys, "manual": MANUAL_SOURCE},
        )
        # An event accepted now supersedes an earlier quarantined version of it.
        conn.execute(
            text(
                "UPDATE corporate_actions_quarantine q SET resolved_at = :now, "
                "resolution = 'superseded' FROM jsonb_to_recordset(CAST(:keys AS jsonb)) "
                "  AS k(stock_id bigint, ex_date date) "
                "WHERE q.resolved_at IS NULL AND q.source = :source "
                "AND q.stock_id = k.stock_id AND q.ex_date = k.ex_date"
            ),
            {"now": utcnow(), "source": source, "keys": keys},
        )
    return stats


def _quarantine(
    conn: Connection,
    action: CorporateAction,
    stock_id: int,
    reasons: list[str],
    source: str,
    raw_object_id: int | None,
) -> None:
    conn.execute(
        text(
            "INSERT INTO corporate_actions_quarantine "
            "(symbol, stock_id, ex_date, action_type, payload, reasons, source, raw_object_id) "
            "VALUES (:symbol, :stock_id, :ex_date, :action_type, CAST(:payload AS jsonb), "
            ":reasons, :source, :raw_object_id) "
            "ON CONFLICT (symbol, ex_date, action_type, source) DO UPDATE SET "
            "payload = excluded.payload, reasons = excluded.reasons, "
            "raw_object_id = excluded.raw_object_id"
        ),
        {
            "symbol": action.symbol,
            "stock_id": stock_id,
            "ex_date": action.ex_date,
            "action_type": action.action_type,
            "payload": json.dumps(action.model_dump(mode="json")),
            "reasons": reasons,
            "source": source,
            "raw_object_id": raw_object_id,
        },
    )


def year_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """[start, end] split at year boundaries (one request per table per year)."""
    chunks = []
    lo = start
    while lo <= end:
        hi = min(end, date(lo.year, 12, 31))
        chunks.append((lo, hi))
        lo = hi + timedelta(days=1)
    return chunks


@register_job
class SyncCorporateActionsJob(Job):
    name: ClassVar[str] = "sync_corporate_actions"
    description: ClassVar[str] = (
        "Import ex-rights/dividends, reductions, par-value changes and ETF splits "
        "(params: start, end; default the past 30 days)"
    )
    uses_date: ClassVar[bool] = False
    timeout: ClassVar[timedelta] = timedelta(hours=2)

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        end = date.fromisoformat(ctx.params.get("end") or taipei_today().isoformat())
        start = date.fromisoformat(ctx.params.get("start") or (end - DEFAULT_LOOKBACK).isoformat())
        resume = (ctx.checkpoint or {}).get("next")
        first = date.fromisoformat(resume) if resume else start
        totals = ActionStats()
        covered: set[str] = set()
        for lo, hi in year_chunks(first, end):
            for market in MARKETS:
                for dataset in DATASETS:
                    since = router.corporate_action_since(market, dataset)
                    if since is None or hi < since:
                        continue
                    covered.add(f"{market}:{dataset}")
                    fetched = router.corporate_actions(market, dataset, lo, hi)
                    with ctx.engine.begin() as conn:
                        stats = store_corporate_actions(
                            conn, fetched.items, fetched.provider, fetched.raw.id
                        )
                    ctx.add_rows(stats.written)
                    totals.add(stats)
            ctx.save_checkpoint({"next": (hi + timedelta(days=1)).isoformat()})
        message = f"{start}～{end}：{totals}"
        uncovered = {f"{m}:{d}" for m in MARKETS for d in DATASETS} - covered
        if uncovered:
            message += f"；沒有官方來源：{'、'.join(sorted(uncovered))}"
        return JobOutcome(message=message)


# ----------------------------------------------------------------------------- details

DETAIL_TYPES = ("cash_and_stock_dividend", "stock_dividend")
"""TWSE event types whose parts the event table leaves out (pure 息 rows carry the cash)."""


def apply_dividend_detail(
    conn: Connection, action_id: int, detail: DividendDetail | None, raw_object_id: int
) -> None:
    """Store the parts, or just the attempt when the page had none (so it is not refetched).

    action_type keeps the exchange's 權/息 label (it is part of the natural key the event
    table is re-imported on); what the event consisted of is in the part columns, e.g. a
    權息 that was cash plus a subscription has stock_dividend_ratio 0 and rights_ratio > 0.
    """
    if detail is None:
        conn.execute(
            text("UPDATE corporate_actions SET detail_raw_object_id = :raw WHERE id = :id"),
            {"raw": raw_object_id, "id": action_id},
        )
        return
    conn.execute(
        text(
            "UPDATE corporate_actions SET detail_raw_object_id = :raw, cash_dividend = :cash, "
            "stock_dividend_ratio = :stock, rights_ratio = :rights, "
            "subscription_price = :price WHERE id = :id"
        ),
        {
            "raw": raw_object_id,
            "id": action_id,
            "cash": detail.cash_dividend,
            "stock": detail.stock_dividend_ratio,
            "rights": detail.rights_ratio,
            "price": detail.subscription_price,
        },
    )


@register_job
class SyncDividendDetailsJob(Job):
    name: ClassVar[str] = "sync_dividend_details"
    description: ClassVar[str] = (
        "Fill cash / stock / rights parts of TWSE 權息 and 權 events from their detail pages "
        "(params: start, end; default the past 30 days; one request per event)"
    )
    uses_date: ClassVar[bool] = False
    timeout: ClassVar[timedelta] = timedelta(hours=6)

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        end = date.fromisoformat(ctx.params.get("end") or taipei_today().isoformat())
        start = date.fromisoformat(ctx.params.get("start") or (end - DEFAULT_LOOKBACK).isoformat())
        since = router.dividend_detail_since("twse")
        if since is None:
            return JobOutcome(message="沒有設定權息明細來源（PROVIDERS_DIVIDEND_DETAILS）")
        with ctx.engine.connect() as conn:
            # Rows without detail_raw_object_id are the work left, so a rerun resumes.
            pending = conn.execute(
                text(
                    "SELECT c.id, s.symbol, c.ex_date FROM corporate_actions c "
                    "JOIN stocks s ON s.id = c.stock_id "
                    "WHERE c.source = 'twse' AND c.action_type IN :types "
                    "AND c.detail_raw_object_id IS NULL "
                    "AND c.ex_date BETWEEN :start AND :end ORDER BY c.ex_date, s.symbol"
                ).bindparams(bindparam("types", expanding=True)),
                {"types": list(DETAIL_TYPES), "start": max(start, since), "end": end},
            ).all()
        filled = missing = 0
        for row in pending:
            fetched = router.dividend_detail("twse", row.symbol, row.ex_date)
            detail = fetched.items[0] if fetched.items else None
            with ctx.engine.begin() as conn:
                apply_dividend_detail(conn, row.id, detail, fetched.raw.id)
            if detail is None:
                missing += 1
            else:
                filled += 1
                ctx.add_rows(1)
        message = f"{start}～{end}：待補 {len(pending)}、補上 {filled}、來源無資料 {missing}"
        return JobOutcome(message=message)


# ----------------------------------------------------------------------------- adj_factor

GAP_RANGE = (Decimal("0.6"), Decimal("1.5"))
"""Adjusted close-to-close moves outside this band exceed any daily price limit (7% before
2015-06, 10% since) by far; they almost always mean an event we have no record of."""
GAP_SOURCE = "derived:price-gap"
UPDATE_BATCH = 2000


def _apply_segments(conn: Connection, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    result = conn.execute(
        text(
            "UPDATE prices_daily p SET adj_factor = v.factor "
            "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) "
            "  AS v(stock_id bigint, lo date, hi date, factor numeric) "
            "WHERE p.stock_id = v.stock_id "
            "AND (v.lo IS NULL OR p.trade_date >= v.lo) AND (v.hi IS NULL OR p.trade_date < v.hi) "
            "AND p.adj_factor <> v.factor"
        ),
        {"rows": json.dumps(rows, default=str)},
    )
    return result.rowcount


def recompute_adj_factors(conn: Connection) -> int:
    """Rewrite prices_daily.adj_factor from corporate_actions; returns rows changed."""
    events: dict[int, list[tuple[date, Decimal]]] = defaultdict(list)
    for row in conn.execute(
        text(
            "SELECT stock_id, ex_date, price_factor FROM corporate_actions "
            "WHERE price_factor IS NOT NULL"
        )
    ):
        events[row.stock_id].append((row.ex_date, row.price_factor))
    changed: int = conn.execute(
        text(
            "UPDATE prices_daily SET adj_factor = 1 WHERE adj_factor <> 1 AND stock_id NOT IN "
            "(SELECT stock_id FROM corporate_actions WHERE price_factor IS NOT NULL)"
        )
    ).rowcount
    batch: list[dict[str, Any]] = []
    for stock_id, stock_events in events.items():
        batch.extend(
            {"stock_id": stock_id, "lo": s.start, "hi": s.end, "factor": s.factor}
            for s in factor_segments(stock_events)
        )
        if len(batch) >= UPDATE_BATCH:
            changed += _apply_segments(conn, batch)
            batch = []
    return changed + _apply_segments(conn, batch)


def gap_payload(prev_day: date, prev_ac: Decimal, ac: Decimal) -> dict[str, Any]:
    """What /admin shows for a gap, with the share ratio that would explain it (if common)."""
    payload: dict[str, Any] = {
        "previous_date": prev_day.isoformat(),
        "previous_adjusted_close": str(prev_ac),
        "adjusted_close": str(ac),
        "ratio": str(round(ac / prev_ac, 4)),
    }
    guess = guess_share_ratio(ac / prev_ac)
    if guess is not None:
        payload["suggestion"] = {
            "ratio": str(guess.ratio),
            "action_type": guess.action_type,
            "implied_move": str(guess.implied_move),
        }
    return payload


def flag_price_gaps(conn: Connection) -> tuple[int, int]:
    """Quarantine unexplained adjusted-price gaps; resolve flags that are explained now.

    Returns (open gaps, newly flagged).
    """
    low, high = GAP_RANGE
    gaps = conn.execute(
        text(
            "WITH b AS ("
            "  SELECT stock_id, trade_date, close * adj_factor AS ac, "
            "         lag(close * adj_factor) OVER w AS prev_ac, lag(trade_date) OVER w AS prev_day"
            "  FROM prices_daily WHERE close IS NOT NULL "
            "  WINDOW w AS (PARTITION BY stock_id ORDER BY trade_date)) "
            "SELECT b.stock_id, s.symbol, b.trade_date, b.prev_day, b.prev_ac, b.ac "
            "FROM b JOIN stocks s ON s.id = b.stock_id "
            "WHERE b.prev_ac IS NOT NULL AND (b.ac / b.prev_ac < :low OR b.ac / b.prev_ac > :high)"
        ),
        {"low": low, "high": high},
    ).all()
    flagged = 0
    for gap in gaps:
        flagged += (
            conn.execute(
                text(
                    "INSERT INTO corporate_actions_quarantine AS q "
                    "(symbol, stock_id, ex_date, action_type, payload, reasons, source) "
                    "VALUES (:symbol, :stock_id, :day, 'unknown', CAST(:payload AS jsonb), "
                    "ARRAY['unexplained_price_gap'], :source) "
                    # Pending flags follow the latest prices and factors; reviewed ones are kept.
                    "ON CONFLICT (symbol, ex_date, action_type, source) DO UPDATE "
                    "SET payload = excluded.payload "
                    "WHERE q.resolved_at IS NULL AND q.payload IS DISTINCT FROM excluded.payload "
                    "RETURNING (xmax = 0) AS inserted"
                ),
                {
                    "symbol": gap.symbol,
                    "stock_id": gap.stock_id,
                    "day": gap.trade_date,
                    "payload": json.dumps(gap_payload(gap.prev_day, gap.prev_ac, gap.ac)),
                    "source": GAP_SOURCE,
                },
            ).scalar()
            is True
        )
    still_open = [{"stock_id": g.stock_id, "day": g.trade_date.isoformat()} for g in gaps]
    conn.execute(
        text(
            "UPDATE corporate_actions_quarantine q "
            "SET resolved_at = :now, resolution = 'explained' "
            "WHERE q.source = :source AND q.resolved_at IS NULL AND NOT EXISTS ("
            "  SELECT 1 FROM jsonb_to_recordset(CAST(:open AS jsonb)) "
            "    AS o(stock_id bigint, day date) "
            "  WHERE o.stock_id = q.stock_id AND o.day = q.ex_date)"
        ),
        {"now": utcnow(), "source": GAP_SOURCE, "open": json.dumps(still_open)},
    )
    return len(gaps), flagged


@register_job
class ComputeAdjFactorsJob(Job):
    name: ClassVar[str] = "compute_adj_factors"
    description: ClassVar[str] = (
        "Rewrite prices_daily.adj_factor from corporate_actions and flag unexplained gaps"
    )
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        with ctx.engine.begin() as conn:
            changed = recompute_adj_factors(conn)
        ctx.add_rows(changed)
        with ctx.engine.begin() as conn:
            open_gaps, flagged = flag_price_gaps(conn)
        gaps = f"無法解釋的價格跳空 {open_gaps} 筆（新標記 {flagged}）"
        return JobOutcome(message=f"更新還原因子 {changed} 筆；{gaps}")
