"""Announced upcoming 除權息 (除權除息預告表), for projected dividends on /portfolio.

The exchanges publish the list as a snapshot (no date parameter), so each run upserts what
it lists and drops future events of the same source that disappeared from it (postponed or
cancelled). Past events stay; corporate_actions is the record of what actually happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar

from sqlalchemy import Connection, bindparam, text

from stockhub.common.db import upsert
from stockhub.common.timeutil import taipei_today
from stockhub.etl.jobs.base import Job, JobContext, JobOutcome, register_job
from stockhub.etl.jobs.market_data import MARKETS, stock_ids_on
from stockhub.etl.providers.base import ExRightsPreview

PART_COLUMNS = [
    "label",
    "action_type",
    "cash_dividend",
    "stock_dividend_ratio",
    "rights_ratio",
    "subscription_price",
]


@dataclass
class PreviewStats:
    received: int = 0
    written: int = 0
    removed: int = 0
    unknown: int = 0

    def __str__(self) -> str:
        return (
            f"收到 {self.received}、寫入 {self.written}、移除 {self.removed}、"
            f"非主檔代號略過 {self.unknown}"
        )


def store_previews(
    conn: Connection,
    previews: list[ExRightsPreview],
    source: str,
    raw_object_id: int | None,
    today: date,
) -> PreviewStats:
    """Upsert one exchange's snapshot and remove its future events no longer listed."""
    stats = PreviewStats(received=len(previews))
    ids = stock_ids_on(conn, today)
    rows: dict[tuple[int, date], dict[str, Any]] = {}
    for v in previews:
        stock_id = ids.get(v.symbol)
        if stock_id is None:
            stats.unknown += 1
            continue
        rows[(stock_id, v.ex_date)] = {
            "stock_id": stock_id,
            "ex_date": v.ex_date,
            "source": source,
            **{c: getattr(v, c) for c in PART_COLUMNS},
            "raw_object_id": raw_object_id,
        }
    stats.written = upsert(
        conn,
        "corporate_action_previews",
        list(rows.values()),
        ["stock_id", "ex_date", "source"],
        PART_COLUMNS,
    )
    listed = [f"{s}:{d.isoformat()}" for s, d in rows]
    removed = conn.execute(
        text(
            "DELETE FROM corporate_action_previews WHERE source = :source AND ex_date >= :today "
            "AND (stock_id::text || ':' || ex_date::text) NOT IN :listed"
        ).bindparams(bindparam("listed", expanding=True)),
        {"source": source, "today": today, "listed": listed or [""]},
    )
    stats.removed = removed.rowcount
    return stats


@register_job
class SyncExRightsPreviewsJob(Job):
    name: ClassVar[str] = "sync_ex_rights_previews"
    description: ClassVar[str] = "Import the TWSE/TPEx 除權除息預告表 (current snapshot)"
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        today = taipei_today()
        parts = []
        for market in MARKETS:
            fetched = router.ex_rights_previews(market)
            with ctx.engine.begin() as conn:
                stats = store_previews(conn, fetched.items, fetched.provider, fetched.raw.id, today)
            ctx.add_rows(stats.written + stats.removed)
            parts.append(f"{market}：{stats}")
        return JobOutcome(message="；".join(parts))
