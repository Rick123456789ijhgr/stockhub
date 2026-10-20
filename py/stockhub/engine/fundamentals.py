"""Single-quarter fundamentals and rule-based signals from as-reported statements.

Inputs are one company's rows of `financials` (every source, every revision) and its
monthly revenue; outputs are the rows of fundamentals_quarterly and fundamental_signals.
Pure functions, no I/O (the job compute_fundamentals does the reading and writing).

Source choice, per period and item (D-084):
- official snapshots (twse, tpex: year-to-date as filed) win over FinMind;
- a single quarter comes from a source's own single-quarter value, or from its year-to-date
  value minus the previous quarter's year-to-date value (any source), or minus the sum of
  the earlier single quarters of the year already derived. Q1 = its year-to-date value;
- balances (instant) take the official value, else FinMind's.
Quarantined statements never reach `financials`, so they are simply absent here.

Ratios are fractions. TTM = the last four single quarters (all four must exist). Averages
for ROE, ROA and DuPont use the balance at period end and four quarters earlier, so that
ROE = net margin x asset turnover x equity multiplier exactly.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from stockhub.common.filings import available_date

OFFICIAL_SOURCES = ("twse", "tpex")
DEFAULT_PAR = Decimal(10)
"""Par value assumed when the company profile states none in TWD (D-084)."""

FLOW_ITEMS = (
    "Revenue",
    "GrossProfit",
    "OperatingIncome",
    "PreTaxIncome",
    "NetIncome",
    "NetIncomeParent",
    "EPS",
    "OperatingCashFlow",
    "CapitalExpenditure",
)
BALANCE_ITEMS = (
    "TotalAssets",
    "CurrentAssets",
    "CurrentLiabilities",
    "TotalLiabilities",
    "EquityParent",
    "Inventories",
    "AccountsReceivable",
    "OrdinaryShare",
    "CapitalStock",
    "BookValuePerShare",
)
STATEMENT_OF = {
    **{i: "IS" for i in FLOW_ITEMS[:7]},
    "OperatingCashFlow": "CF",
    "CapitalExpenditure": "CF",
    **{i: "BS" for i in BALANCE_ITEMS},
}


@dataclass(frozen=True)
class Row:
    """One row of financials."""

    period_end: date
    statement: str
    item_code: str
    value: Decimal
    basis: str
    source: str
    revision: int = 0
    publish_date: date | None = None


@dataclass
class Quarter:
    """One output row of fundamentals_quarterly (column name -> value)."""

    period_end: date
    values: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> Any:
        return self.values.get(key)


@dataclass(frozen=True)
class Signal:
    code: str
    period_end: date
    direction: str
    title: str
    detail: dict[str, Any]


# ----------------------------------------------------------------------------- helpers


def _quarter_index(day: date) -> int:
    """Consecutive quarter number (year * 4 + quarter - 1)."""
    return day.year * 4 + (day.month - 1) // 3


def _quarter_end(index: int) -> date:
    year, q = divmod(index, 4)
    month = 3 * (q + 1)
    return date(year, month, 31 if month in (3, 12) else 30)


def _div(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _avg(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None or b is None:
        return None
    return (a + b) / 2


def _growth(now: Decimal | None, before: Decimal | None) -> Decimal | None:
    """now / before - 1, only against a positive base."""
    if now is None or before is None or before <= 0:
        return None
    return now / before - 1


def _source_rank(source: str) -> int:
    return 0 if source in OFFICIAL_SOURCES else 1


def latest_revisions(rows: Iterable[Row]) -> list[Row]:
    best: dict[tuple[date, str, str, str], Row] = {}
    for row in rows:
        key = (row.period_end, row.statement, row.item_code, row.source)
        if key not in best or row.revision > best[key].revision:
            best[key] = row
    return list(best.values())


# ----------------------------------------------------------------------------- single quarters


class _Item:
    """All sources' values of one item, indexed by quarter."""

    def __init__(self) -> None:
        self.by_source: dict[str, dict[int, tuple[str, Decimal]]] = defaultdict(dict)

    def add(self, row: Row) -> None:
        self.by_source[row.source][_quarter_index(row.period_end)] = (row.basis, row.value)

    def sources(self) -> list[str]:
        return sorted(self.by_source, key=lambda s: (_source_rank(s), s))

    def ytd(self, index: int, prefer: str) -> Decimal | None:
        """Year-to-date value at a quarter from `prefer`, else any source."""
        for source in [prefer, *self.sources()]:
            entry = self.by_source.get(source, {}).get(index)
            if entry is not None and entry[0] == "ytd":
                return entry[1]
        return None


def single_quarters(item: _Item) -> dict[int, tuple[Decimal, str]]:
    """Quarter index -> (single-quarter value, source used)."""
    indices = sorted({i for values in item.by_source.values() for i in values})
    out: dict[int, tuple[Decimal, str]] = {}
    for index in indices:
        q = index % 4
        for source in item.sources():
            entry = item.by_source[source].get(index)
            if entry is None:
                continue
            basis, value = entry
            if basis == "quarter":
                out[index] = (value, source)
                break
            if basis != "ytd":
                continue
            if q == 0:
                out[index] = (value, source)
                break
            previous = item.ytd(index - 1, source)
            if previous is None:
                earlier = [out.get(i) for i in range(index - q, index)]
                if all(e is not None for e in earlier):
                    previous = sum((e[0] for e in earlier if e is not None), Decimal(0))
            if previous is not None:
                out[index] = (value - previous, source)
                break
    return out


def instants(item: _Item) -> dict[int, tuple[Decimal, str]]:
    out: dict[int, tuple[Decimal, str]] = {}
    for source in reversed(item.sources()):  # best source written last
        for index, (basis, value) in item.by_source[source].items():
            if basis == "instant":
                out[index] = (value, source)
    return out


# ----------------------------------------------------------------------------- quarters


def _ttm(series: dict[int, Decimal], index: int) -> Decimal | None:
    values = [series.get(i) for i in range(index - 3, index + 1)]
    if any(v is None for v in values):
        return None
    return sum((v for v in values if v is not None), Decimal(0))


def compute_quarters(rows: Iterable[Row], par_value: Decimal | None = None) -> list[Quarter]:
    """fundamentals_quarterly rows of one company, oldest first."""
    rows = latest_revisions(rows)
    items: dict[str, _Item] = defaultdict(_Item)
    publish: dict[int, date] = {}
    for row in rows:
        items[row.item_code].add(row)
        if row.publish_date is not None and row.source in OFFICIAL_SOURCES:
            index = _quarter_index(row.period_end)
            publish[index] = min(publish.get(index, row.publish_date), row.publish_date)

    flows: dict[str, dict[int, Decimal]] = {}
    flow_sources: dict[str, dict[int, str]] = {}
    for code in FLOW_ITEMS:
        derived = single_quarters(items[code]) if code in items else {}
        flows[code] = {i: v for i, (v, _) in derived.items()}
        flow_sources[code] = {i: s for i, (_, s) in derived.items()}
    balances: dict[str, dict[int, Decimal]] = {}
    balance_sources: dict[str, dict[int, str]] = {}
    for code in BALANCE_ITEMS:
        found = instants(items[code]) if code in items else {}
        balances[code] = {i: v for i, (v, _) in found.items()}
        balance_sources[code] = {i: s for i, (_, s) in found.items()}

    indices = sorted(
        set().union(*(set(s) for s in flows.values()), *(set(s) for s in balances.values()))
    )
    par = par_value if par_value and par_value > 0 else DEFAULT_PAR
    out: list[Quarter] = []
    for index in indices:
        period_end = _quarter_end(index)
        f = {code: series.get(index) for code, series in flows.items()}
        b = {code: series.get(index) for code, series in balances.items()}
        b_prev = {code: series.get(index - 4) for code, series in balances.items()}
        capex = -f["CapitalExpenditure"] if f["CapitalExpenditure"] is not None else None
        fcf = (
            f["OperatingCashFlow"] - capex
            if f["OperatingCashFlow"] is not None and capex is not None
            else None
        )
        common = b["OrdinaryShare"] if b["OrdinaryShare"] is not None else b["CapitalStock"]
        shares = common / par if common is not None and common > 0 else None
        bvps = b["BookValuePerShare"]
        if bvps is None:
            bvps = _div(b["EquityParent"], shares)

        revenue_ttm = _ttm(flows["Revenue"], index)
        nip_ttm = _ttm(flows["NetIncomeParent"], index)
        ni_ttm = _ttm(flows["NetIncome"], index)
        ocf_ttm = _ttm(flows["OperatingCashFlow"], index)
        capex_ttm = _ttm(flows["CapitalExpenditure"], index)
        fcf_ttm = ocf_ttm + capex_ttm if ocf_ttm is not None and capex_ttm is not None else None
        avg_assets = _avg(b["TotalAssets"], b_prev["TotalAssets"])
        avg_equity = _avg(b["EquityParent"], b_prev["EquityParent"])
        if avg_equity is not None and avg_equity <= 0:
            avg_equity = None  # negative equity: ratios are meaningless

        revenue_prev = flows["Revenue"].get(index - 4)
        eps_prev = flows["EPS"].get(index - 4)
        eps_yoy = (
            (f["EPS"] - eps_prev) / abs(eps_prev)
            if f["EPS"] is not None and eps_prev is not None and eps_prev != 0
            else None
        )
        values: dict[str, Any] = {
            "revenue": f["Revenue"],
            "gross_profit": f["GrossProfit"],
            "operating_income": f["OperatingIncome"],
            "pretax_income": f["PreTaxIncome"],
            "net_income": f["NetIncome"],
            "net_income_parent": f["NetIncomeParent"],
            "eps": f["EPS"],
            "operating_cash_flow": f["OperatingCashFlow"],
            "capital_expenditure": capex,
            "free_cash_flow": fcf,
            "revenue_ttm": revenue_ttm,
            "net_income_parent_ttm": nip_ttm,
            "eps_ttm": _ttm(flows["EPS"], index),
            "operating_cash_flow_ttm": ocf_ttm,
            "free_cash_flow_ttm": fcf_ttm,
            "total_assets": b["TotalAssets"],
            "current_assets": b["CurrentAssets"],
            "current_liabilities": b["CurrentLiabilities"],
            "total_liabilities": b["TotalLiabilities"],
            "equity_parent": b["EquityParent"],
            "inventories": b["Inventories"],
            "accounts_receivable": b["AccountsReceivable"],
            "shares": shares,
            "bvps": bvps,
            "gross_margin": _div(f["GrossProfit"], f["Revenue"])
            if (f["Revenue"] or 0) > 0
            else None,
            "operating_margin": (
                _div(f["OperatingIncome"], f["Revenue"]) if (f["Revenue"] or 0) > 0 else None
            ),
            "net_margin": _div(f["NetIncome"], f["Revenue"]) if (f["Revenue"] or 0) > 0 else None,
            "roe_ttm": _div(nip_ttm, avg_equity),
            "roa_ttm": _div(ni_ttm, avg_assets),
            "dupont_net_margin": _div(nip_ttm, revenue_ttm) if (revenue_ttm or 0) > 0 else None,
            "dupont_asset_turnover": _div(revenue_ttm, avg_assets),
            "dupont_equity_multiplier": _div(avg_assets, avg_equity),
            "debt_ratio": _div(b["TotalLiabilities"], b["TotalAssets"]),
            "current_ratio": _div(b["CurrentAssets"], b["CurrentLiabilities"]),
            "revenue_yoy": _growth(f["Revenue"], revenue_prev),
            "eps_yoy": eps_yoy,
            "publish_date": publish.get(index),
            "available_date": available_date(period_end, publish.get(index)),
        }
        sources: dict[str, str] = {}
        for statement, codes in (
            ("IS", ("Revenue", "NetIncomeParent", "EPS")),
            ("CF", ("OperatingCashFlow",)),
        ):
            used = {flow_sources[c].get(index) for c in codes} - {None}
            if used:
                sources[statement] = "+".join(sorted(s for s in used if s))
        used_bs = {balance_sources[c].get(index) for c in ("TotalAssets", "EquityParent")} - {None}
        if used_bs:
            sources["BS"] = "+".join(sorted(s for s in used_bs if s))
        out.append(Quarter(period_end, values, sources))
    return out


# ----------------------------------------------------------------------------- signals

MARGIN_SWING = Decimal("0.03")
"""Gross / operating margin change against the same quarter a year earlier (3 points)."""
REVENUE_SWING = Decimal("0.30")
INVENTORY_GAP = Decimal("0.30")
"""Inventory (or receivables) growing this much faster than TTM revenue, year over year."""
INVENTORY_MIN_SHARE = Decimal("0.05")
"""...and making up at least this share of total assets, so small balances do not fire."""
FCF_STREAK = 4
RECORD_MIN_MONTHS = 24


def _pct(value: Decimal) -> str:
    return f"{value * 100:.1f}%"


def _points(value: Decimal) -> str:
    return f"{value * 100:+.1f} 個百分點"


def quarter_signals(quarters: Sequence[Quarter]) -> list[Signal]:
    by_index = {_quarter_index(q.period_end): q for q in quarters}
    out: list[Signal] = []
    for index, q in sorted(by_index.items()):
        prev = by_index.get(index - 4)
        label = f"{q.period_end.year}Q{index % 4 + 1}"
        if prev is not None:
            for key, name in (("gross_margin", "毛利率"), ("operating_margin", "營業利益率")):
                now, before = q.get(key), prev.get(key)
                if now is None or before is None:
                    continue
                change = now - before
                if abs(change) >= MARGIN_SWING:
                    out.append(
                        Signal(
                            f"{key}_yoy",
                            q.period_end,
                            "up" if change > 0 else "down",
                            f"{label} {name} {_pct(now)}，年比 {_points(change)}",
                            {"now": str(now), "year_ago": str(before)},
                        )
                    )
            ni, ni_before = q.get("net_income_parent"), prev.get("net_income_parent")
            if ni is not None and ni_before is not None:
                if ni_before <= 0 < ni:
                    out.append(
                        Signal(
                            "turn_profit", q.period_end, "up", f"{label} 轉盈（去年同期虧損）", {}
                        )
                    )
                elif ni_before > 0 >= ni:
                    out.append(
                        Signal(
                            "turn_loss", q.period_end, "down", f"{label} 轉虧（去年同期獲利）", {}
                        )
                    )
            growth = q.get("revenue_yoy")
            if growth is not None and abs(growth) >= REVENUE_SWING:
                out.append(
                    Signal(
                        "revenue_yoy",
                        q.period_end,
                        "up" if growth > 0 else "down",
                        f"{label} 營收年增 {_pct(growth)}",
                        {"yoy": str(growth)},
                    )
                )
            out.extend(_balance_growth_signals(q, prev, label))
        streak = [by_index.get(i) for i in range(index - FCF_STREAK + 1, index + 1)]
        fcfs = [s.get("free_cash_flow") if s else None for s in streak]
        if all(v is not None and v < 0 for v in fcfs):
            before = by_index.get(index - FCF_STREAK)
            before_fcf = before.get("free_cash_flow") if before else None
            # Report the streak once, when it reaches its length.
            if before_fcf is None or before_fcf >= 0:
                out.append(
                    Signal(
                        "fcf_negative_streak",
                        q.period_end,
                        "down",
                        f"{label} 自由現金流連續 {FCF_STREAK} 季為負",
                        {},
                    )
                )
    return out


def _balance_growth_signals(q: Quarter, prev: Quarter, label: str) -> list[Signal]:
    out: list[Signal] = []
    revenue_growth = _growth(q.get("revenue_ttm"), prev.get("revenue_ttm"))
    assets = q.get("total_assets")
    if revenue_growth is None or not assets:
        return out
    for key, name in (("inventories", "存貨"), ("accounts_receivable", "應收帳款")):
        now, before = q.get(key), prev.get(key)
        growth = _growth(now, before)
        if growth is None or now / assets < INVENTORY_MIN_SHARE:
            continue
        if growth - revenue_growth >= INVENTORY_GAP:
            out.append(
                Signal(
                    f"{key}_vs_revenue",
                    q.period_end,
                    "down",
                    f"{label} {name}年增 {_pct(growth)}，"
                    f"遠高於近四季營收年增 {_pct(revenue_growth)}",
                    {"growth": str(growth), "revenue_growth": str(revenue_growth)},
                )
            )
    return out


def revenue_signals(months: dict[date, Decimal]) -> list[Signal]:
    """Monthly rules: record high (after two years of history), big year-over-year swings."""
    out: list[Signal] = []
    best: Decimal | None = None
    ordered = sorted(months.items())
    for count, (month, revenue) in enumerate(ordered, 1):
        label = f"{month.year} 年 {month.month} 月"
        if best is not None and revenue > best and count > RECORD_MIN_MONTHS:
            out.append(
                Signal(
                    "revenue_record",
                    month,
                    "up",
                    f"{label} 營收創歷史新高",
                    {"revenue": str(revenue), "previous_high": str(best)},
                )
            )
        best = revenue if best is None else max(best, revenue)
        year_ago = months.get(date(month.year - 1, month.month, 1))
        growth = _growth(revenue, year_ago)
        if growth is not None and abs(growth) >= REVENUE_SWING:
            out.append(
                Signal(
                    "revenue_month_yoy",
                    month,
                    "up" if growth > 0 else "down",
                    f"{label} 營收年增 {_pct(growth)}",
                    {"yoy": str(growth)},
                )
            )
    return out
