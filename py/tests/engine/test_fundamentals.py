"""Single-quarterization, TTM, ratios and signals (engine/fundamentals.py)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from stockhub.engine.fundamentals import (
    Quarter,
    Row,
    compute_quarters,
    quarter_signals,
    revenue_signals,
)

D = Decimal
Q = {
    "2025Q1": date(2025, 3, 31),
    "2025Q2": date(2025, 6, 30),
    "2025Q3": date(2025, 9, 30),
    "2025Q4": date(2025, 12, 31),
    "2026Q1": date(2026, 3, 31),
    "2026Q2": date(2026, 6, 30),
}


def _is(
    period: str, revenue: int, eps: str, source: str = "finmind", basis: str = "quarter"
) -> list[Row]:
    p = Q[period]
    return [
        Row(p, "IS", "Revenue", D(revenue), basis, source),
        Row(p, "IS", "GrossProfit", D(revenue) * D("0.4"), basis, source),
        Row(p, "IS", "NetIncomeParent", D(revenue) * D("0.1"), basis, source),
        Row(p, "IS", "NetIncome", D(revenue) * D("0.1"), basis, source),
        Row(p, "IS", "EPS", D(eps), basis, source),
    ]


def _bs(period: str, assets: int, equity: int, source: str = "finmind") -> list[Row]:
    p = Q[period]
    return [
        Row(p, "BS", "TotalAssets", D(assets), "instant", source),
        Row(p, "BS", "TotalLiabilities", D(assets - equity), "instant", source),
        Row(p, "BS", "EquityParent", D(equity), "instant", source),
        Row(p, "BS", "OrdinaryShare", D(100), "instant", source),
    ]


def _cf(period: str, ocf_ytd: int, capex_ytd: int) -> list[Row]:
    p = Q[period]
    return [
        Row(p, "CF", "OperatingCashFlow", D(ocf_ytd), "ytd", "finmind"),
        Row(p, "CF", "CapitalExpenditure", D(-capex_ytd), "ytd", "finmind"),
    ]


@pytest.fixture
def rows() -> list[Row]:
    out: list[Row] = []
    for period, revenue, eps in [
        ("2025Q1", 100, "1.0"),
        ("2025Q2", 110, "1.1"),
        ("2025Q3", 120, "1.2"),
        ("2025Q4", 130, "1.3"),
        ("2026Q1", 140, "1.4"),
    ]:
        out += _is(period, revenue, eps)
    # Official year-to-date for 2026 H1 (FinMind's 2026Q2 was quarantined): Q2 = 290 - 140.
    out += _is("2026Q2", 290, "2.9", source="twse", basis="ytd")
    for period, assets, equity in [
        ("2025Q1", 1000, 500),
        ("2025Q2", 1000, 500),
        ("2025Q3", 1100, 550),
        ("2025Q4", 1100, 550),
        ("2026Q1", 1200, 600),
        ("2026Q2", 1200, 600),
    ]:
        out += _bs(period, assets, equity)
    for period, ocf, capex in [
        ("2025Q1", 10, 5),
        ("2025Q2", 25, 10),
        ("2025Q3", 45, 15),
        ("2025Q4", 70, 20),
        ("2026Q1", 30, 8),
    ]:
        out += _cf(period, ocf, capex)
    return out


def _by_period(quarters: list[Quarter]) -> dict[date, Quarter]:
    return {q.period_end: q for q in quarters}


def test_single_quarters_from_quarter_and_ytd_sources(rows: list[Row]) -> None:
    q = _by_period(compute_quarters(rows))
    assert q[Q["2026Q2"]].get("revenue") == D(150)
    assert q[Q["2026Q2"]].get("eps") == D("1.5")
    assert q[Q["2026Q2"]].sources["IS"] == "twse"
    assert q[Q["2026Q1"]].sources["IS"] == "finmind"
    # Cash flow is year-to-date as filed: Q4 = 70 - 45, capex is reported as spending.
    assert q[Q["2025Q4"]].get("operating_cash_flow") == D(25)
    assert q[Q["2025Q4"]].get("capital_expenditure") == D(5)
    assert q[Q["2025Q4"]].get("free_cash_flow") == D(20)
    assert q[Q["2026Q1"]].get("operating_cash_flow") == D(30)  # Q1 = its year-to-date


def test_ttm_needs_four_quarters(rows: list[Row]) -> None:
    q = _by_period(compute_quarters(rows))
    assert q[Q["2025Q3"]].get("revenue_ttm") is None
    assert q[Q["2025Q4"]].get("revenue_ttm") == D(460)
    assert q[Q["2026Q2"]].get("revenue_ttm") == D(540)  # 120 + 130 + 140 + 150
    assert q[Q["2026Q2"]].get("eps_ttm") == D("5.4")
    assert q[Q["2025Q4"]].get("free_cash_flow_ttm") == D(50)


def test_roe_equals_dupont_product(rows: list[Row]) -> None:
    q = _by_period(compute_quarters(rows))[Q["2026Q2"]]
    roe = q.get("roe_ttm")
    product = (
        q.get("dupont_net_margin")
        * q.get("dupont_asset_turnover")
        * q.get("dupont_equity_multiplier")
    )
    assert roe == D("54") / D("550")  # TTM parent income 54 / average equity (600 + 500) / 2
    assert abs(roe - product) < D("1e-20")
    assert q.get("debt_ratio") == D("0.5")
    assert q.get("gross_margin") == D("0.4")
    assert q.get("revenue_yoy") == D(150) / D(110) - 1


def test_shares_bvps_and_par_value(rows: list[Row]) -> None:
    q = _by_period(compute_quarters(rows))[Q["2026Q2"]]
    assert q.get("shares") == D(10)  # common stock 100 / par 10
    assert q.get("bvps") == D(60)
    half = _by_period(compute_quarters(rows, par_value=D(5)))[Q["2026Q2"]]
    assert half.get("bvps") == D(30)
    official = [*rows, Row(Q["2026Q2"], "BS", "BookValuePerShare", D("59.9"), "instant", "twse")]
    assert _by_period(compute_quarters(official))[Q["2026Q2"]].get("bvps") == D("59.9")


def test_available_date_uses_publish_date_or_deadline(rows: list[Row]) -> None:
    published = [
        Row(r.period_end, r.statement, r.item_code, r.value, r.basis, r.source, 0, date(2026, 8, 7))
        if r.source == "twse"
        else r
        for r in rows
    ]
    q = _by_period(compute_quarters(published))
    assert q[Q["2026Q2"]].get("available_date") == date(2026, 8, 7)
    assert q[Q["2026Q2"]].get("publish_date") == date(2026, 8, 7)
    assert q[Q["2025Q4"]].get("available_date") == date(2026, 3, 31)  # annual deadline


def test_latest_revision_wins(rows: list[Row]) -> None:
    restated = [*rows, Row(Q["2026Q1"], "IS", "Revenue", D(141), "quarter", "finmind", 1)]
    q = _by_period(compute_quarters(restated))
    assert q[Q["2026Q1"]].get("revenue") == D(141)


def test_quarter_signals(rows: list[Row]) -> None:
    quarters = compute_quarters(rows)
    q2 = _by_period(quarters)[Q["2026Q2"]]
    q2.values["gross_margin"] = D("0.45")  # +5 points on the year
    q2.values["net_income_parent"] = D(-1)
    codes = {
        (s.code, s.direction) for s in quarter_signals(quarters) if s.period_end == Q["2026Q2"]
    }
    assert ("gross_margin_yoy", "up") in codes
    assert ("turn_loss", "down") in codes
    assert ("revenue_yoy", "up") in codes  # 150 vs 110 = +36%


def test_fcf_streak_is_reported_once() -> None:
    periods = ["2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1"]
    quarters = [Quarter(Q[p], {"free_cash_flow": D(-1)}) for p in periods]
    streaks = [s for s in quarter_signals(quarters) if s.code == "fcf_negative_streak"]
    assert [s.period_end for s in streaks] == [date(2025, 12, 31)]


def test_revenue_record_and_month_yoy() -> None:
    months = {date(2023 + (m // 12), m % 12 + 1, 1): D(100) for m in range(30)}
    months[date(2025, 6, 1)] = D(150)
    signals = revenue_signals(months)
    assert {(s.code, s.period_end) for s in signals} == {
        ("revenue_record", date(2025, 6, 1)),
        ("revenue_month_yoy", date(2025, 6, 1)),
    }
