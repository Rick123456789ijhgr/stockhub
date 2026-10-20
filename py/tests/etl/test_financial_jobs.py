"""Fundamentals ingest jobs against recorded FinMind and OpenAPI responses (no network)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, text

from stockhub.common.notifier import ConsoleNotifier
from stockhub.common.rawstore import LocalRawStore
from stockhub.etl.jobs.base import JobRunResult, run_job
from stockhub.etl.jobs.financials import month_revenue_context, store_statements
from stockhub.etl.providers.base import FinancialItem
from stockhub.etl.providers.finmind import FinMindProvider, QuotaGuard
from stockhub.etl.providers.http import make_client
from stockhub.etl.providers.registry import ProviderRegistry
from stockhub.etl.providers.router import ProviderRouter, RateLimiter, RetryPolicy
from stockhub.etl.providers.tpex import TpexProvider
from stockhub.etl.providers.twse import TwseProvider
from stockhub.etl.quality import check_statement

from .official_sources import fixture

D = Decimal
FINMIND_FIXTURES = {
    "TaiwanStockFinancialStatements": "finmind_is_2330.json",
    "TaiwanStockBalanceSheet": "finmind_bs_2330.json",
    "TaiwanStockCashFlowsStatement": "finmind_cf_2330.json",
    "TaiwanStockMonthRevenue": "finmind_revenue_2330.json",
}


class Handler:
    """OpenAPI snapshots from fixtures; FinMind data for 2330 only (empty for others)."""

    def __init__(self) -> None:
        self.finmind: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if "finmindtrade" in request.url.host:
            params = request.url.params
            self.finmind.append((params["dataset"], params["data_id"]))
            if params["data_id"] != "2330":
                return httpx.Response(200, json={"msg": "success", "status": 200, "data": []})
            return httpx.Response(200, content=fixture(FINMIND_FIXTURES[params["dataset"]]))
        tail = request.url.path.rsplit("/", 1)[-1]
        prefix = "twse_" if tail.startswith("t187") else "tpex_"
        return httpx.Response(200, content=fixture(f"{prefix}{tail}.json"))


@pytest.fixture
def handler() -> Handler:
    return Handler()


@pytest.fixture
def router(clean_db: Engine, tmp_path: Path, handler: Handler) -> ProviderRouter:
    client = make_client(httpx.MockTransport(handler))
    twse, tpex = TwseProvider(client), TpexProvider(client)
    finmind = FinMindProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        token="t",
        guard=QuotaGuard(500, lambda: None, sleep=lambda _: None),
    )
    registry = ProviderRegistry(
        {
            "financial": [finmind],
            "monthly_revenue": [finmind],
            "financial_snapshot": [twse, tpex],
            "monthly_revenue_snapshot": [twse, tpex],
            "company_profiles": [twse, tpex],
        }
    )
    return ProviderRouter(
        registry,
        LocalRawStore(clean_db, tmp_path),
        retry=RetryPolicy(max_attempts=1, base_delay=0, jitter=0),
        limiter=RateLimiter(clock=lambda: 0.0, sleep=lambda _: None),
        sleep=lambda _: None,
    )


@pytest.fixture
def stocks(clean_db: Engine) -> dict[str, int]:
    with clean_db.begin() as conn:
        rows = conn.execute(
            text(
                "INSERT INTO stocks (symbol, market, type, name, listed_date) VALUES "
                "('1101', 'twse', 'stock', '台泥', '1962-02-09'), "
                "('2330', 'twse', 'stock', '台積電', '1994-09-05'), "
                "('1240', 'tpex', 'stock', '茂生農經', '2018-08-08'), "
                "('0050', 'twse', 'etf', '元大台灣50', '2003-06-30') RETURNING symbol, id"
            )
        ).all()
    return {r.symbol: r.id for r in rows}


def _run(
    clean_db: Engine, router: ProviderRouter, job: str, params: dict[str, Any] | None = None
) -> JobRunResult:
    result = run_job(
        job,
        params or {},
        engine=clean_db,
        rawstore=router.rawstore,
        notifier=ConsoleNotifier(),
        router=router,
    )
    assert result.status == "succeeded", result.error
    return result


def test_backfill_writes_finmind_history_and_quarantines_mislabeled_quarter(
    clean_db: Engine, router: ProviderRouter, handler: Handler, stocks: dict[str, int]
) -> None:
    first = _run(clean_db, router, "backfill_fundamentals", {"symbols": "2330"})
    assert handler.finmind == [
        ("TaiwanStockMonthRevenue", "2330"),
        ("TaiwanStockFinancialStatements", "2330"),
        ("TaiwanStockBalanceSheet", "2330"),
        ("TaiwanStockCashFlowsStatement", "2330"),
    ]
    tsmc = stocks["2330"]
    with clean_db.connect() as conn:
        revenue = conn.execute(
            text(
                "SELECT value, basis FROM financials WHERE stock_id = :s AND item_code = 'Revenue' "
                "AND period_end = '2025-12-31'"
            ),
            {"s": tsmc},
        ).one()
        quarantined = conn.execute(
            text("SELECT period_end, statement, reasons FROM financials_quarantine")
        ).all()
        states = conn.execute(
            text("SELECT dataset, last_period FROM financial_fetch_state ORDER BY dataset")
        ).all()
        months = conn.execute(
            text("SELECT count(*), min(revenue_month) FROM monthly_revenue WHERE stock_id = :s"),
            {"s": tsmc},
        ).one()
    assert revenue == (D("1046090421000.0"), "quarter")
    # FinMind's latest income statement carries year-to-date revenue (see D-083).
    assert [(q.period_end, q.statement, q.reasons) for q in quarantined] == [
        (date(2026, 6, 30), "IS", ["ytd_as_quarter"])
    ]
    assert {s.dataset: s.last_period for s in states} == {
        "BS": date(2026, 6, 30),
        "CF": date(2026, 6, 30),
        "IS": date(2026, 6, 30),  # latest in the response, even though quarantined
        "monthly_revenue": date(2026, 9, 1),
    }
    assert months[1] == date(2024, 12, 1)  # FinMind's `date` is the following month
    assert first.rows_written > 0

    handler.finmind.clear()
    again = _run(clean_db, router, "backfill_fundamentals", {"symbols": "2330"})
    assert handler.finmind == []  # resumes from financial_fetch_state
    assert again.rows_written == 0
    refetched = _run(
        clean_db, router, "backfill_fundamentals", {"symbols": "2330", "refetch": "true"}
    )
    assert refetched.rows_written == 0  # identical values write nothing (rule 4)


def test_changed_value_is_a_new_revision_and_clean_refetch_supersedes(
    clean_db: Engine, stocks: dict[str, int]
) -> None:
    def item(value: str, code: str = "Revenue", basis: str = "quarter") -> FinancialItem:
        return FinancialItem(
            symbol="2330",
            period_end=date(2026, 6, 30),
            statement="IS",
            item_code=code,
            value=D(value),
            basis=basis,  # type: ignore[arg-type]
        )

    tsmc = stocks["2330"]
    context = {date(2026, 6, 30): (D(100), D(210))}
    with clean_db.begin() as conn:
        bad = store_statements(conn, tsmc, [item("210")], "finmind", None, revenue_context=context)
        good = store_statements(conn, tsmc, [item("100")], "finmind", None, revenue_context=context)
        fixed = store_statements(
            conn, tsmc, [item("101")], "finmind", None, revenue_context=context
        )
        rows = conn.execute(text("SELECT revision, value FROM financials ORDER BY revision")).all()
        resolution = conn.execute(text("SELECT resolution FROM financials_quarantine")).scalar()
    assert (bad.quarantined, bad.written) == (1, 0)
    assert (good.superseded, good.written) == (1, 1)
    assert (fixed.written, fixed.revisions) == (1, 1)
    assert [(r.revision, r.value) for r in rows] == [(0, D(100)), (1, D(101))]
    assert resolution == "superseded"


def test_sync_financials_stores_snapshots_then_refreshes_new_filers(
    clean_db: Engine, router: ProviderRouter, handler: Handler, stocks: dict[str, int]
) -> None:
    result = _run(clean_db, router, "sync_financials")
    with clean_db.connect() as conn:
        official = conn.execute(
            text(
                "SELECT s.symbol, f.source, f.basis, f.value, f.publish_date FROM financials f "
                "JOIN stocks s ON s.id = f.stock_id "
                "WHERE f.item_code = 'Revenue' AND f.source IN ('twse', 'tpex') ORDER BY 1"
            )
        ).all()
    assert [(r.symbol, r.source, r.basis) for r in official] == [
        ("1101", "twse", "ytd"),
        ("1240", "tpex", "ytd"),
        ("2330", "twse", "ytd"),
    ]
    # First seen long after the 08-14 deadline: filed while we were not watching.
    assert all(r.publish_date is None for r in official)
    # Every company with a new official quarter is asked once per statement (ETFs never).
    asked = {symbol for _, symbol in handler.finmind}
    assert asked == {"1101", "2330", "1240"}
    assert "FinMind 更新 3 家" in (result.message or "")

    handler.finmind.clear()
    _run(clean_db, router, "sync_financials")
    # 1101 and 1240 had nothing at FinMind: not asked again within REFRESH_AFTER.
    assert handler.finmind == []


def test_first_seen_publish_date_within_grace(clean_db: Engine, stocks: dict[str, int]) -> None:
    item = FinancialItem(
        symbol="1101",
        period_end=date(2026, 6, 30),
        statement="BS",
        item_code="TotalAssets",
        value=D(1),
        basis="instant",
    )
    with clean_db.begin() as conn:
        store_statements(
            conn, stocks["1101"], [item], "twse", None, official=True, today=date(2026, 8, 12)
        )
        publish = conn.execute(text("SELECT publish_date FROM financials")).scalar()
    assert publish == date(2026, 8, 12)


def test_monthly_revenue_official_wins_and_keeps_publish_date(
    clean_db: Engine, router: ProviderRouter, stocks: dict[str, int]
) -> None:
    _run(
        clean_db,
        router,
        "backfill_fundamentals",
        {"symbols": "2330", "datasets": "monthly_revenue"},
    )
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "UPDATE monthly_revenue SET revenue = 1 WHERE stock_id = :s "
                "AND revenue_month = '2026-09-01'"
            ),
            {"s": stocks["2330"]},
        )
    _run(clean_db, router, "sync_monthly_revenue")
    with clean_db.connect() as conn:
        row = conn.execute(
            text(
                "SELECT revenue, source, publish_date FROM monthly_revenue WHERE stock_id = :s "
                "AND revenue_month = '2026-09-01'"
            ),
            {"s": stocks["2330"]},
        ).one()
        ctx = month_revenue_context(conn, stocks["2330"])
    assert row.source == "twse"
    assert row.revenue > 1
    assert row.publish_date == date(2026, 10, 8)  # FinMind's create_time is kept
    assert ctx[date(2026, 6, 30)][1] > ctx[date(2026, 6, 30)][0]  # H1 vs Q2 sums


def test_sync_company_profiles(
    clean_db: Engine, router: ProviderRouter, stocks: dict[str, int]
) -> None:
    first = _run(clean_db, router, "sync_company_profiles")
    with clean_db.connect() as conn:
        row = conn.execute(
            text("SELECT par_value, issued_shares, industry_code FROM stocks WHERE symbol = '1101'")
        ).one()
    assert row == (D(10), 7523181742, "01")
    assert first.rows_written == 3
    assert _run(clean_db, router, "sync_company_profiles").rows_written == 0


@pytest.mark.parametrize(
    ("statement", "basis", "values", "context", "expected"),
    [
        (
            "BS",
            "instant",
            {"TotalAssets": D(100), "TotalLiabilities": D(40), "TotalEquity": D(60)},
            None,
            [],
        ),
        (
            "BS",
            "instant",
            {"TotalAssets": D(100), "TotalLiabilities": D(40), "TotalEquity": D(50)},
            None,
            ["unbalanced"],
        ),
        ("IS", "quarter", {"Revenue": D(210)}, (D(100), D(210)), ["ytd_as_quarter"]),
        ("IS", "quarter", {"Revenue": D(101)}, (D(100), D(210)), []),
        ("IS", "quarter", {"Revenue": D(100)}, (D(100), D(100)), []),  # Q1: both sums equal
        ("IS", "ytd", {"Revenue": D(210)}, (D(100), D(210)), []),
        ("IS", "quarter", {"Revenue": D(-5)}, None, ["negative_revenue"]),
    ],
)
def test_check_statement(
    statement: str,
    basis: str,
    values: dict[str, Decimal],
    context: tuple[Decimal, Decimal] | None,
    expected: list[str],
) -> None:
    assert check_statement(statement, basis, values, context) == expected
