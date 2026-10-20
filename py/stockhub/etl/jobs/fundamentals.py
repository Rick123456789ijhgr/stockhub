"""compute_fundamentals: rebuild fundamentals_quarterly and fundamental_signals per company.

Derived data only (engine/fundamentals.py); each company is deleted and rewritten in one
transaction, so a rerun gives the same rows (rule 4). By default only companies whose
statements or revenue arrived after their last computation are rebuilt.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import ClassVar

from sqlalchemy import Connection, text
from sqlalchemy.dialects.postgresql import insert

from stockhub.common.db import get_table
from stockhub.common.timeutil import utcnow
from stockhub.engine.fundamentals import Row, compute_quarters, quarter_signals, revenue_signals
from stockhub.etl.jobs.base import Job, JobContext, JobOutcome, register_job


def load_rows(conn: Connection, stock_id: int) -> list[Row]:
    return [
        Row(
            r.period_end,
            r.statement,
            r.item_code,
            Decimal(r.value),
            r.basis,
            r.source,
            r.revision,
            r.publish_date,
        )
        for r in conn.execute(
            text(
                "SELECT period_end, statement, item_code, value, basis, source, revision, "
                "publish_date FROM financials WHERE stock_id = :s"
            ),
            {"s": stock_id},
        )
    ]


def compute_company(conn: Connection, stock_id: int) -> tuple[int, int]:
    """Rebuild one company; returns (quarters, signals) written."""
    par = conn.execute(
        text("SELECT par_value FROM stocks WHERE id = :s"), {"s": stock_id}
    ).scalar_one_or_none()
    quarters = compute_quarters(load_rows(conn, stock_id), par)
    months: dict[date, Decimal] = {
        r.revenue_month: Decimal(r.revenue)
        for r in conn.execute(
            text("SELECT revenue_month, revenue FROM monthly_revenue WHERE stock_id = :s"),
            {"s": stock_id},
        )
    }
    signals = quarter_signals(quarters) + revenue_signals(months)
    now = utcnow()
    conn.execute(text("DELETE FROM fundamentals_quarterly WHERE stock_id = :s"), {"s": stock_id})
    conn.execute(text("DELETE FROM fundamental_signals WHERE stock_id = :s"), {"s": stock_id})
    if quarters:
        conn.execute(
            insert(get_table(conn, "fundamentals_quarterly")).values(
                [
                    {
                        "stock_id": stock_id,
                        "period_end": q.period_end,
                        **q.values,
                        "sources": q.sources,
                        "computed_at": now,
                    }
                    for q in quarters
                ]
            )
        )
    if signals:
        unique = {(s.code, s.period_end): s for s in signals}
        conn.execute(
            insert(get_table(conn, "fundamental_signals")).values(
                [
                    {
                        "stock_id": stock_id,
                        "code": s.code,
                        "period_end": s.period_end,
                        "direction": s.direction,
                        "title": s.title,
                        "detail": s.detail,
                        "computed_at": now,
                    }
                    for s in unique.values()
                ]
            )
        )
    return len(quarters), len(signals)


def stale_companies(conn: Connection, symbols: list[str], everything: bool) -> list[int]:
    return list(
        conn.execute(
            text(
                "WITH inputs AS ("
                "  SELECT stock_id, max(fetched_at) AS at FROM financials GROUP BY stock_id "
                "  UNION ALL "
                "  SELECT stock_id, max(fetched_at) FROM monthly_revenue GROUP BY stock_id), "
                "latest_input AS (SELECT stock_id, max(at) AS at FROM inputs GROUP BY stock_id), "
                "outputs AS ("
                "  SELECT stock_id, max(computed_at) AS at FROM fundamentals_quarterly "
                "  GROUP BY stock_id "
                "  UNION ALL "
                "  SELECT stock_id, max(computed_at) FROM fundamental_signals GROUP BY stock_id), "
                "latest_output AS (SELECT stock_id, max(at) AS at FROM outputs GROUP BY stock_id) "
                "SELECT i.stock_id FROM latest_input i "
                "JOIN stocks s ON s.id = i.stock_id "
                "LEFT JOIN latest_output o ON o.stock_id = i.stock_id "
                "WHERE (:all OR o.at IS NULL OR o.at < i.at) "
                "AND (cardinality(CAST(:symbols AS text[])) = 0 OR s.symbol = ANY(:symbols)) "
                "ORDER BY i.stock_id"
            ),
            {"all": everything or bool(symbols), "symbols": symbols},
        ).scalars()
    )


@register_job
class ComputeFundamentalsJob(Job):
    name: ClassVar[str] = "compute_fundamentals"
    description: ClassVar[str] = (
        "Rebuild derived fundamentals and signals of companies with new data "
        "(params: symbols, all=true for every company)"
    )
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        symbols = [s.strip() for s in str(ctx.params.get("symbols") or "").split(",") if s.strip()]
        everything = str(ctx.params.get("all", "")).lower() in ("1", "true", "yes")
        with ctx.engine.connect() as conn:
            companies = stale_companies(conn, symbols, everything)
        quarters = signals = 0
        for stock_id in companies:
            with ctx.engine.begin() as conn:
                q, s = compute_company(conn, stock_id)
            quarters += q
            signals += s
        ctx.add_rows(quarters + signals)
        return JobOutcome(message=f"{len(companies)} 家：{quarters} 季、{signals} 則提示")
