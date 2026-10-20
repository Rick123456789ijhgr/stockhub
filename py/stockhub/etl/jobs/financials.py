"""Fundamentals ingest: company profiles, statement and monthly revenue history, daily refresh.

Sources (D-082):
- history: FinMind, one request per company and dataset, from 2013 (IFRS);
- daily: the exchanges' OpenAPI snapshots of the latest filed quarter and revenue month
  (official, whole market in a few requests). Companies that appear there with a quarter we
  do not have from FinMind yet are then refreshed from FinMind (cash flow statements and the
  single-quarter income statement only come from there).

Each source keeps its own rows in financials; a value that changes becomes a new revision.
Statements failing check_statement go to financials_quarantine as a whole (rule 7).
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, ClassVar, Literal

from sqlalchemy import Connection, func, text
from sqlalchemy.dialects.postgresql import insert

from stockhub.common.db import get_table, upsert
from stockhub.common.filings import first_seen_publish_date, quarter_deadline, revenue_deadline
from stockhub.common.timeutil import taipei_today, utcnow
from stockhub.etl.jobs.base import Job, JobContext, JobError, JobOutcome, register_job
from stockhub.etl.jobs.fundamentals import compute_company
from stockhub.etl.jobs.market_data import MARKETS, stock_ids_on
from stockhub.etl.providers.base import (
    AllProvidersFailedError,
    FinancialItem,
    MonthlyRevenue,
    Statement,
)
from stockhub.etl.providers.router import ProviderRouter
from stockhub.etl.quality import LIABILITY_ITEMS, check_statement, suspect_liabilities

log = logging.getLogger(__name__)

HISTORY_START = date(2013, 1, 1)
"""User decision: history back to 2013, the first IFRS year."""
STATEMENTS: tuple[Statement, ...] = ("IS", "BS", "CF")
Dataset = Literal["IS", "BS", "CF", "monthly_revenue"]
DATASETS: tuple[Dataset, ...] = ("monthly_revenue", "IS", "BS", "CF")
"""Revenue first: the income statement check compares quarters with the months."""
MAX_CONSECUTIVE_FAILURES = 20
"""That many failed fetches in a row is a systemic problem (token, source down): stop."""


# ----------------------------------------------------------------------------- statements


@dataclass
class StatementStats:
    written: int = 0
    revisions: int = 0
    quarantined: int = 0
    superseded: int = 0

    def add(self, other: StatementStats) -> None:
        self.written += other.written
        self.revisions += other.revisions
        self.quarantined += other.quarantined
        self.superseded += other.superseded

    def __str__(self) -> str:
        return (
            f"寫入 {self.written}（其中修正 {self.revisions}）、隔離 {self.quarantined} 份、"
            f"取代隔離 {self.superseded} 份"
        )


def _latest_values(
    conn: Connection, stock_id: int, source: str
) -> dict[tuple[date, str, str], tuple[int, Decimal]]:
    rows = conn.execute(
        text(
            "SELECT DISTINCT ON (period_end, statement, item_code) period_end, statement, "
            "item_code, revision, value FROM financials WHERE stock_id = :s AND source = :src "
            "ORDER BY period_end, statement, item_code, revision DESC"
        ),
        {"s": stock_id, "src": source},
    ).all()
    return {(r.period_end, r.statement, r.item_code): (r.revision, r.value) for r in rows}


QUARTER_MONTHS = {3: (1, 2, 3), 6: (4, 5, 6), 9: (7, 8, 9), 12: (10, 11, 12)}


def month_revenue_context(conn: Connection, stock_id: int) -> dict[date, tuple[Decimal, Decimal]]:
    """Quarter end -> (sum of its three months, sum of the year up to it) where all are known."""
    by_month = {
        r.revenue_month: r.revenue
        for r in conn.execute(
            text("SELECT revenue_month, revenue FROM monthly_revenue WHERE stock_id = :s"),
            {"s": stock_id},
        )
    }
    out: dict[date, tuple[Decimal, Decimal]] = {}
    for year in {m.year for m in by_month}:
        for end_month, months in QUARTER_MONTHS.items():
            quarter = [by_month.get(date(year, m, 1)) for m in months]
            ytd = [by_month.get(date(year, m, 1)) for m in range(1, end_month + 1)]
            if all(v is not None for v in ytd):
                q_end = date(year, end_month, 31 if end_month in (3, 12) else 30)
                out[q_end] = (
                    sum((v for v in quarter if v is not None), Decimal(0)),
                    sum((v for v in ytd if v is not None), Decimal(0)),
                )
    return out


def store_statements(
    conn: Connection,
    stock_id: int,
    items: Iterable[FinancialItem],
    source: str,
    raw_object_id: int | None,
    *,
    official: bool = False,
    today: date | None = None,
    revenue_context: dict[date, tuple[Decimal, Decimal]] | None = None,
) -> StatementStats:
    """Write one company's items from one source, statement by statement.

    Unchanged values write nothing; a changed value is the next revision. Official snapshot
    rows get a first-seen publish date (see filings.first_seen_publish_date); restatements
    seen later are dated the day they were seen.
    """
    today = today or taipei_today()
    stats = StatementStats()
    groups: dict[tuple[date, Statement], list[FinancialItem]] = defaultdict(list)
    for item in items:
        groups[(item.period_end, item.statement)].append(item)
    if not groups:
        return stats
    latest = _latest_values(conn, stock_id, source)
    rows: list[dict[str, Any]] = []
    for (period_end, statement), group in sorted(groups.items()):
        values = {i.item_code: i.value for i in group}
        basis = group[0].basis
        context = (revenue_context or {}).get(period_end) if statement == "IS" else None
        reasons = check_statement(statement, basis, values, context)
        key = {"s": stock_id, "p": period_end, "st": statement, "src": source}
        held = group
        if reasons == ["unbalanced"] and suspect_liabilities(values):
            # Keep the sound items; only the liability figures wait for review.
            held = [i for i in group if i.item_code in LIABILITY_ITEMS]
            group = [i for i in group if i.item_code not in LIABILITY_ITEMS]
            reasons = ["liabilities_inconsistent"]
        if reasons:
            payload = [
                {"item_code": i.item_code, "value": str(i.value), "basis": i.basis} for i in held
            ]
            changed = conn.execute(
                text(
                    "INSERT INTO financials_quarantine (stock_id, period_end, statement, source, "
                    "payload, reasons, raw_object_id) VALUES (:s, :p, :st, :src, "
                    "CAST(:payload AS jsonb), :reasons, :raw) "
                    "ON CONFLICT (stock_id, period_end, statement, source) DO UPDATE SET "
                    "payload = excluded.payload, reasons = excluded.reasons, "
                    "raw_object_id = excluded.raw_object_id, created_at = now(), "
                    "resolved_at = NULL, resolution = NULL "
                    "WHERE financials_quarantine.payload IS DISTINCT FROM excluded.payload"
                ),
                {**key, "payload": json.dumps(payload), "reasons": reasons, "raw": raw_object_id},
            ).rowcount
            stats.quarantined += 1 if changed else 0
            if held is group:
                continue
        else:
            stats.superseded += conn.execute(
                text(
                    "UPDATE financials_quarantine SET resolved_at = now(), "
                    "resolution = 'superseded' WHERE stock_id = :s AND period_end = :p "
                    "AND statement = :st AND source = :src AND resolved_at IS NULL"
                ),
                key,
            ).rowcount
        for item in group:
            previous = latest.get((period_end, statement, item.item_code))
            if previous is not None and previous[1] == item.value:
                continue
            revision = previous[0] + 1 if previous is not None else 0
            publish: date | None = None
            if official:
                publish = (
                    today
                    if previous is not None
                    else first_seen_publish_date(today, quarter_deadline(period_end))
                )
            stats.revisions += 1 if previous is not None else 0
            rows.append(
                {
                    "stock_id": stock_id,
                    "period_end": period_end,
                    "period_type": item.period_type,
                    "statement": statement,
                    "item_code": item.item_code,
                    "value": item.value,
                    "basis": item.basis,
                    "publish_date": publish,
                    "revision": revision,
                    "source": source,
                    "raw_object_id": raw_object_id,
                }
            )
    if rows:
        stats.written += upsert(
            conn,
            "financials",
            rows,
            ["stock_id", "period_end", "statement", "item_code", "source", "revision"],
            [],
        )
    return stats


# ----------------------------------------------------------------------------- monthly revenue


def store_monthly_revenue(
    conn: Connection,
    rows: Sequence[tuple[int, MonthlyRevenue]],
    source: str,
    raw_object_id: int | None,
    *,
    official: bool,
    today: date | None = None,
) -> int:
    """Upsert (stock_id, month) revenues. Official values win over FinMind ones; a known
    publish date is never replaced."""
    if not rows:
        return 0
    today = today or taipei_today()
    now = utcnow()
    values = []
    for stock_id, item in rows:
        publish = item.publish_date
        if official and publish is None:
            publish = first_seen_publish_date(today, revenue_deadline(item.revenue_month))
        values.append(
            {
                "stock_id": stock_id,
                "revenue_month": item.revenue_month,
                "revenue": item.revenue,
                "publish_date": publish,
                "source": source,
                "raw_object_id": raw_object_id,
                "fetched_at": now,
            }
        )
    table = get_table(conn, "monthly_revenue")
    stmt = insert(table).values(values)
    current = table.c
    changed = current.revenue.is_distinct_from(stmt.excluded.revenue) | (
        current.publish_date.is_(None) & stmt.excluded.publish_date.isnot(None)
    )
    allowed = changed if official else (current.source == source) & changed
    stmt = stmt.on_conflict_do_update(
        index_elements=["stock_id", "revenue_month"],
        set_={
            "revenue": stmt.excluded.revenue,
            "source": stmt.excluded.source,
            "raw_object_id": stmt.excluded.raw_object_id,
            "fetched_at": stmt.excluded.fetched_at,
            "publish_date": func.coalesce(current.publish_date, stmt.excluded.publish_date),
        },
        where=allowed,
    )
    return len(conn.execute(stmt.returning(current.stock_id)).all())


# ----------------------------------------------------------------------------- fetch state


def record_fetch(
    conn: Connection, stock_id: int, dataset: Dataset, source: str, last_period: date | None
) -> None:
    upsert(
        conn,
        "financial_fetch_state",
        [
            {
                "stock_id": stock_id,
                "dataset": dataset,
                "source": source,
                "fetched_at": utcnow(),
                "last_period": last_period,
            }
        ],
        ["stock_id", "dataset", "source"],
    )


@dataclass
class HistoryStats:
    statements: StatementStats = field(default_factory=StatementStats)
    revenue_rows: int = 0
    requests: int = 0
    empty: int = 0
    failures: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"請求 {self.requests}、財報 {self.statements}、月營收 {self.revenue_rows} 筆、"
            f"無資料 {self.empty}、失敗 {len(self.failures)}"
        )


@dataclass(frozen=True)
class Company:
    id: int
    symbol: str


def fetch_company_history(
    conn_factory: Any,
    router: ProviderRouter,
    company: Company,
    datasets: Sequence[Dataset],
    start: date,
    stats: HistoryStats,
) -> int:
    """Fetch and store the given datasets of one company; returns consecutive failures
    at the end (0 when the last fetch worked)."""
    failures = 0
    for dataset in datasets:
        stats.requests += 1
        try:
            if dataset == "monthly_revenue":
                revenue = router.monthly_revenue(company.symbol, start)
                with conn_factory() as conn:
                    months = [(company.id, m) for m in revenue.items if m.revenue_month >= start]
                    stats.revenue_rows += store_monthly_revenue(
                        conn, months, revenue.provider, revenue.raw.id, official=False
                    )
                    last = max((m.revenue_month for _, m in months), default=None)
                    record_fetch(conn, company.id, dataset, revenue.provider, last)
            else:
                statement = router.financials(company.symbol, dataset, start)
                with conn_factory() as conn:
                    items = [i for i in statement.items if i.period_end >= start]
                    stats.statements.add(
                        store_statements(
                            conn,
                            company.id,
                            items,
                            statement.provider,
                            statement.raw.id,
                            revenue_context=month_revenue_context(conn, company.id),
                        )
                    )
                    last = max((i.period_end for i in items), default=None)
                    record_fetch(conn, company.id, dataset, statement.provider, last)
        except AllProvidersFailedError as exc:
            failures += 1
            stats.failures.append(f"{company.symbol} {dataset}: {exc}")
            log.warning("history %s %s failed: %s", company.symbol, dataset, exc)
            continue
        failures = 0
        stats.empty += last is None
    return failures


def history_companies(conn: Connection, start: date, symbols: Sequence[str] = ()) -> list[Company]:
    """Stocks (not ETFs) alive at some point since `start`: held or watched first, then
    listed, then delisted. A reused symbol is fetched for its current listing only, since the
    source knows a company by its symbol."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT ON (s.symbol) s.id, s.symbol, s.delisted_date, "
            "  (EXISTS (SELECT 1 FROM portfolio_transactions t WHERE t.stock_id = s.id) "
            "   OR EXISTS (SELECT 1 FROM watchlist w WHERE w.stock_id = s.id)) AS mine "
            "FROM stocks s WHERE s.type = 'stock' "
            "AND (s.delisted_date IS NULL OR s.delisted_date >= :start) "
            "AND (cardinality(CAST(:symbols AS text[])) = 0 OR s.symbol = ANY(:symbols)) "
            "ORDER BY s.symbol, s.delisted_date DESC NULLS FIRST"
        ),
        {"start": start, "symbols": list(symbols)},
    ).all()
    ordered = sorted(rows, key=lambda r: (not r.mine, r.delisted_date is not None, r.symbol))
    return [Company(r.id, r.symbol) for r in ordered]


def fetched_datasets(conn: Connection, source: str) -> set[tuple[int, str]]:
    return {
        (r.stock_id, r.dataset)
        for r in conn.execute(
            text("SELECT stock_id, dataset FROM financial_fetch_state WHERE source = :s"),
            {"s": source},
        )
    }


def _parse_list(value: object) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


@register_job
class BackfillFundamentalsJob(Job):
    name: ClassVar[str] = "backfill_fundamentals"
    description: ClassVar[str] = (
        "Statement and monthly revenue history of every stock since 2013 from FinMind "
        "(params: start, symbols, datasets, refetch; resumable; ~17 h on the free tier)"
    )
    uses_date: ClassVar[bool] = False
    timeout: ClassVar[timedelta] = timedelta(hours=30)

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        start = date.fromisoformat(ctx.params.get("start") or HISTORY_START.isoformat())
        symbols = _parse_list(ctx.params.get("symbols"))
        wanted = _parse_list(ctx.params.get("datasets")) or list(DATASETS)
        unknown = set(wanted) - set(DATASETS)
        if unknown:
            raise JobError(f"未知的資料集：{sorted(unknown)}（可用：{', '.join(DATASETS)}）")
        datasets: list[Dataset] = [d for d in DATASETS if d in wanted]
        refetch = str(ctx.params.get("refetch", "")).lower() in ("1", "true", "yes")
        source = router.registry.providers_for("financial")[0].name
        with ctx.engine.connect() as conn:
            companies = history_companies(conn, start, symbols)
            done = set() if refetch else fetched_datasets(conn, source)
        stats = HistoryStats()
        consecutive = 0
        for index, company in enumerate(companies, 1):
            todo = [d for d in datasets if (company.id, d) not in done]
            if todo:
                failed = fetch_company_history(
                    ctx.engine.begin, router, company, todo, start, stats
                )
                consecutive = consecutive + failed if failed else 0
                if consecutive >= MAX_CONSECUTIVE_FAILURES:
                    raise JobError(
                        f"連續 {consecutive} 次抓取失敗，先停止（最後：{stats.failures[-1]}）"
                    )
            ctx.rows_written = stats.statements.written + stats.revenue_rows
            ctx.save_checkpoint({"done": index, "total": len(companies), "symbol": company.symbol})
        return JobOutcome(message=f"{len(companies)} 檔：{stats}")


# ----------------------------------------------------------------------------- daily refresh


@register_job
class SyncCompanyProfilesJob(Job):
    name: ClassVar[str] = "sync_company_profiles"
    description: ClassVar[str] = "Par value, issued shares and industry code of listed companies"
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        counts = []
        for market in MARKETS:
            fetched = router.company_profiles(market)
            with ctx.engine.begin() as conn:
                ids = stock_ids_on(conn, taipei_today())
                changed = 0
                for profile in fetched.items:
                    stock_id = ids.get(profile.symbol)
                    if stock_id is None:
                        continue
                    changed += conn.execute(
                        text(
                            "UPDATE stocks SET par_value = :par, issued_shares = :shares, "
                            "industry_code = :code WHERE id = :id AND "
                            "(par_value, issued_shares, industry_code) IS DISTINCT FROM "
                            "(CAST(:par AS numeric), CAST(:shares AS bigint), CAST(:code AS text))"
                        ),
                        {
                            "par": profile.par_value,
                            "shares": profile.issued_shares,
                            "code": profile.industry_code,
                            "id": stock_id,
                        },
                    ).rowcount
            ctx.add_rows(changed)
            counts.append(f"{market} {len(fetched.items)} 家（更新 {changed}）")
        return JobOutcome(message="公司基本資料：" + "、".join(counts))


REFRESH_AFTER = timedelta(hours=20)
"""Ask FinMind again about a company at most this often (it may lag the filing by days)."""
QUARANTINE_RETRY_AFTER = timedelta(days=3)


def refresh_targets(conn: Connection, source: str, limit: int) -> list[Company]:
    """Companies whose latest official quarter FinMind has not delivered yet, plus those with
    a pending FinMind quarantine (FinMind may fix its numbers), held or watched first.
    While backfill_fundamentals runs, companies it has not reached yet are left to it."""
    now = utcnow()
    backfilling = conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM job_runs WHERE job_name = 'backfill_fundamentals' "
            "AND status = 'running')"
        )
    ).scalar_one()
    rows = conn.execute(
        text(
            "WITH official AS ("
            "  SELECT stock_id, max(period_end) AS period FROM financials "
            "  WHERE source IN ('twse', 'tpex') GROUP BY stock_id), "
            "state AS (SELECT stock_id, last_period, fetched_at FROM financial_fetch_state "
            "  WHERE source = :src AND dataset = 'IS'), "
            "pending AS (SELECT DISTINCT stock_id FROM financials_quarantine "
            "  WHERE source = :src AND resolved_at IS NULL) "
            "SELECT s.id, s.symbol, "
            "  (EXISTS (SELECT 1 FROM portfolio_transactions t WHERE t.stock_id = s.id) "
            "   OR EXISTS (SELECT 1 FROM watchlist w WHERE w.stock_id = s.id)) AS mine "
            "FROM stocks s "
            "LEFT JOIN official o ON o.stock_id = s.id "
            "LEFT JOIN state st ON st.stock_id = s.id "
            "LEFT JOIN pending q ON q.stock_id = s.id "
            "WHERE s.delisted_date IS NULL AND s.type = 'stock' AND ("
            "  (o.period IS NOT NULL AND (st.last_period IS NULL OR st.last_period < o.period) "
            "   AND NOT (:backfilling AND st.stock_id IS NULL) "
            "   AND (st.fetched_at IS NULL OR st.fetched_at < :refresh)) "
            "  OR (q.stock_id IS NOT NULL AND (st.fetched_at IS NULL OR st.fetched_at < :retry))) "
            "ORDER BY mine DESC, s.symbol LIMIT :limit"
        ),
        {
            "src": source,
            "backfilling": backfilling,
            "refresh": now - REFRESH_AFTER,
            "retry": now - QUARANTINE_RETRY_AFTER,
            "limit": limit,
        },
    ).all()
    return [Company(r.id, r.symbol) for r in rows]


@register_job
class SyncFinancialsJob(Job):
    name: ClassVar[str] = "sync_financials"
    description: ClassVar[str] = (
        "Official snapshots of the latest filed quarter, then FinMind for companies that just "
        "filed (params: max_requests, default 600)"
    )
    uses_date: ClassVar[bool] = False
    timeout: ClassVar[timedelta] = timedelta(hours=3)

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        today = taipei_today()
        official = StatementStats()
        for market in MARKETS:
            for statement in ("IS", "BS"):
                fetched = router.financial_snapshot(market, statement)
                by_symbol: dict[str, list[FinancialItem]] = defaultdict(list)
                for item in fetched.items:
                    by_symbol[item.symbol].append(item)
                with ctx.engine.begin() as conn:
                    ids = stock_ids_on(conn, today)
                    for symbol, items in by_symbol.items():
                        stock_id = ids.get(symbol)
                        if stock_id is not None:
                            official.add(
                                store_statements(
                                    conn,
                                    stock_id,
                                    items,
                                    fetched.provider,
                                    fetched.raw.id,
                                    official=True,
                                    today=today,
                                )
                            )
        ctx.add_rows(official.written)
        max_requests = int(ctx.params.get("max_requests", 600))
        source = router.registry.providers_for("financial")[0].name
        with ctx.engine.connect() as conn:
            targets = refresh_targets(conn, source, max_requests // len(STATEMENTS))
        stats = HistoryStats()
        start = date(today.year - 1, 1, 1)
        for company in targets:
            fetch_company_history(ctx.engine.begin, router, company, STATEMENTS, start, stats)
            ctx.rows_written = official.written + stats.statements.written
            if len(stats.failures) >= MAX_CONSECUTIVE_FAILURES:
                break
        return JobOutcome(message=f"官方快照：{official}；FinMind 更新 {len(targets)} 家：{stats}")


@register_job
class SyncMonthlyRevenueJob(Job):
    name: ClassVar[str] = "sync_monthly_revenue"
    description: ClassVar[str] = "Latest monthly revenue of every listed company (official)"
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        today = taipei_today()
        parts = []
        for market in MARKETS:
            fetched = router.monthly_revenue_snapshot(market)
            with ctx.engine.begin() as conn:
                ids = stock_ids_on(conn, today)
                rows = [(ids[m.symbol], m) for m in fetched.items if m.symbol in ids]
                written = store_monthly_revenue(
                    conn, rows, fetched.provider, fetched.raw.id, official=True, today=today
                )
            ctx.add_rows(written)
            months = sorted({m.revenue_month.isoformat()[:7] for m in fetched.items})
            parts.append(f"{market} {len(rows)} 家 {'、'.join(months)}（寫入 {written}）")
        return JobOutcome(message="月營收：" + "；".join(parts))


@register_job
class RefreshStockFundamentalsJob(Job):
    name: ClassVar[str] = "refresh_stock_fundamentals"
    description: ClassVar[str] = (
        "Re-fetch one company's statements and monthly revenue since 2013 (params: symbol)"
    )
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        router = ctx.require_router()
        symbol = str(ctx.params.get("symbol") or "").strip()
        with ctx.engine.connect() as conn:
            companies = history_companies(conn, HISTORY_START, [symbol]) if symbol else []
        if not companies:
            raise JobError(f"找不到股票代號 {symbol!r}（ETF 沒有財報）")
        stats = HistoryStats()
        fetch_company_history(
            ctx.engine.begin, router, companies[0], DATASETS, HISTORY_START, stats
        )
        ctx.rows_written = stats.statements.written + stats.revenue_rows
        if stats.failures:
            raise JobError("；".join(stats.failures))
        with ctx.engine.begin() as conn:
            quarters, signals = compute_company(conn, companies[0].id)
        return JobOutcome(message=f"{symbol}：{stats}；重算 {quarters} 季、{signals} 則提示")


@register_job
class RecheckFinancialsQuarantineJob(Job):
    name: ClassVar[str] = "recheck_financials_quarantine"
    description: ClassVar[str] = (
        "Run the current quality checks again over pending quarantined statements (no "
        "network; after a check changes): passing items move to financials"
    )
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        with ctx.engine.connect() as conn:
            pending = conn.execute(
                text(
                    "SELECT q.id, q.stock_id, s.symbol, q.period_end, q.statement, q.source, "
                    "q.payload, q.raw_object_id FROM financials_quarantine q "
                    "JOIN stocks s ON s.id = q.stock_id WHERE q.resolved_at IS NULL ORDER BY q.id"
                )
            ).all()
        stats = StatementStats()
        for row in pending:
            items = [
                FinancialItem(
                    symbol=row.symbol,
                    period_end=row.period_end,
                    statement=row.statement,
                    item_code=i["item_code"],
                    value=Decimal(i["value"]),
                    basis=i["basis"],
                )
                for i in row.payload
            ]
            with ctx.engine.begin() as conn:
                stats.add(
                    store_statements(
                        conn,
                        row.stock_id,
                        items,
                        row.source,
                        row.raw_object_id,
                        official=row.source in ("twse", "tpex"),
                        revenue_context=month_revenue_context(conn, row.stock_id),
                    )
                )
        ctx.add_rows(stats.written)
        return JobOutcome(message=f"重新檢查 {len(pending)} 份：{stats}")
