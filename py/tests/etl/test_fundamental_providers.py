"""FinMind and the exchanges' MOPS OpenAPI datasets: parsing, units, quota handling."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from stockhub.etl.providers.base import RawResponse, TransientProviderError
from stockhub.etl.providers.finmind import FinMindProvider, QuotaGuard
from stockhub.etl.providers.http import make_client
from stockhub.etl.providers.mops_openapi import par_value
from stockhub.etl.providers.tpex import TpexProvider
from stockhub.etl.providers.twse import TwseProvider
from tests.etl.official_sources import fixture


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _no_wait_guard() -> QuotaGuard:
    clock = FakeClock()
    return QuotaGuard(500, lambda: None, clock=clock, sleep=clock.sleep)


def _finmind(handler: httpx.MockTransport | None = None) -> FinMindProvider:
    client = httpx.Client(transport=handler) if handler else None
    return FinMindProvider(client=client, token="t0k3n", guard=_no_wait_guard())


# ----------------------------------------------------------------------------- FinMind parsing


def test_finmind_income_statement_is_single_quarter_under_canonical_codes() -> None:
    raw = RawResponse(
        "TaiwanStockFinancialStatements",
        fixture("finmind_is_2330.json"),
        {"symbol": "2330", "statement": "IS"},
    )
    items = _finmind().parse_financials(raw)
    by_key = {(i.period_end, i.item_code): i for i in items}
    revenue = by_key[(date(2025, 12, 31), "Revenue")]
    assert revenue.basis == "quarter"
    assert revenue.statement == "IS"
    assert revenue.value == Decimal("1046090421000.0")
    assert by_key[(date(2025, 12, 31), "EPS")].value == Decimal("19.51")
    # The IS and BS both call parent-owner items EquityAttributableToOwnersOfParent.
    assert (date(2025, 12, 31), "NetIncomeParent") in by_key
    assert all(i.item_code != "EquityParent" for i in items)


def test_finmind_balance_sheet_skips_percent_items_and_cash_flow_is_ytd() -> None:
    bs = _finmind().parse_financials(
        RawResponse("TaiwanStockBalanceSheet", fixture("finmind_bs_2330.json"), {"statement": "BS"})
    )
    codes = {i.item_code for i in bs}
    assert {"TotalAssets", "EquityParent", "OrdinaryShare"} <= codes
    assert all(i.basis == "instant" for i in bs)
    assert not any(c.endswith("_per") for c in codes)
    cf = _finmind().parse_financials(
        RawResponse(
            "TaiwanStockCashFlowsStatement", fixture("finmind_cf_2330.json"), {"statement": "CF"}
        )
    )
    capex = {i.period_end: i.value for i in cf if i.item_code == "CapitalExpenditure"}
    assert all(i.basis == "ytd" for i in cf)
    assert capex[date(2025, 12, 31)] < capex[date(2025, 9, 30)] < 0  # year-to-date grows


def test_finmind_monthly_revenue_months_and_publish_dates() -> None:
    raw = RawResponse("TaiwanStockMonthRevenue", fixture("finmind_revenue_2330.json"), {})
    months = {m.revenue_month: m for m in _finmind().parse_monthly_revenue(raw)}
    latest = months[date(2026, 9, 1)]
    assert latest.revenue == Decimal(511857399000)
    assert latest.publish_date == date(2026, 10, 8)
    assert months[date(2024, 12, 1)].publish_date is None  # FinMind only dates recent months


def test_finmind_error_message_is_a_parse_error() -> None:
    raw = RawResponse("x", json.dumps({"msg": "Your level is register", "status": 400}), {})
    with pytest.raises(ValueError, match="level"):
        _finmind().parse_financials(RawResponse(raw.dataset, raw.payload, {"statement": "IS"}))


# ----------------------------------------------------------------------------- FinMind HTTP


def test_finmind_sends_token_in_header_and_waits_out_the_hourly_limit() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(
                402, json={"msg": "Requests reach the upper limit", "status": 402}
            )
        return httpx.Response(200, content=fixture("finmind_revenue_2330.json"))

    clock = FakeClock(start=3600 * 10 + 1200)  # 20 minutes past an hour
    guard = QuotaGuard(500, lambda: None, clock=clock, sleep=clock.sleep)
    provider = FinMindProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)), token="t0k3n", guard=guard
    )
    raw = provider.fetch_monthly_revenue("2330", date(2013, 1, 1))
    assert len(seen) == 2
    assert seen[0].headers["Authorization"] == "Bearer t0k3n"
    assert "t0k3n" not in str(seen[0].url)
    assert seen[0].url.params["start_date"] == "2013-01-01"
    assert clock.slept == [2400 + 60]  # to one minute past the next full hour
    assert raw.params == {"symbol": "2330", "start": "2013-01-01"}


def test_finmind_limit_twice_is_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"msg": "Requests reach the upper limit", "status": 402})

    provider = _finmind(httpx.MockTransport(handler))
    with pytest.raises(TransientProviderError, match="limit"):
        provider.fetch_financials("2330", "IS", date(2013, 1, 1))


def test_quota_guard_caps_the_rolling_hour() -> None:
    clock = FakeClock()
    guard = QuotaGuard(3, lambda: None, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        guard.acquire()
        clock.now += 10
    guard.acquire()  # the 4th request waits until the first leaves the window
    assert clock.slept == [3600 - 30]


def test_quota_guard_waits_while_the_account_is_near_its_limit() -> None:
    clock = FakeClock()
    usage = iter([(560, 600), (100, 600)])
    guard = QuotaGuard(500, lambda: next(usage), clock=clock, sleep=clock.sleep, wait_step=300)
    guard.acquire()
    assert clock.slept == [300]  # 560 >= min(500, 540): wait one step, then re-check


# ----------------------------------------------------------------------------- MOPS OpenAPI


def _mops_handler(request: httpx.Request) -> httpx.Response:
    tail = request.url.path.rsplit("/", 1)[-1]
    prefix = "twse_" if tail.startswith("t187") else "tpex_"
    return httpx.Response(200, content=fixture(f"{prefix}{tail}.json"))


def test_twse_snapshot_is_ytd_in_twd() -> None:
    twse = TwseProvider(client=make_client(httpx.MockTransport(_mops_handler)))
    raw = twse.fetch_financial_snapshot("twse", "IS")
    items = {(i.symbol, i.item_code): i for i in twse.parse_financial_snapshot(raw)}
    revenue = items[("1101", "Revenue")]
    assert revenue.period_end == date(2026, 6, 30)
    assert revenue.basis == "ytd"
    assert revenue.value == Decimal("71289957000")  # thousands -> TWD
    assert items[("1101", "EPS")].value == Decimal("0.38")  # per share: unscaled
    bs = twse.parse_financial_snapshot(twse.fetch_financial_snapshot("twse", "BS"))
    bvps = {i.symbol: i.value for i in bs if i.item_code == "BookValuePerShare"}
    assert bvps["1101"] == Decimal("30.86")
    assert all(i.basis == "instant" for i in bs)


def test_tpex_snapshot_mixed_keys_and_revenue_month() -> None:
    tpex = TpexProvider(client=make_client(httpx.MockTransport(_mops_handler)))
    is_items = tpex.parse_financial_snapshot(tpex.fetch_financial_snapshot("tpex", "IS"))
    assert {i.symbol for i in is_items} == {"1240", "5483"}
    bs = tpex.parse_financial_snapshot(tpex.fetch_financial_snapshot("tpex", "BS"))
    assert any(i.item_code == "EquityParent" and i.symbol == "1240" for i in bs)
    revenue = tpex.parse_monthly_revenue_snapshot(tpex.fetch_monthly_revenue_snapshot("tpex"))
    first = next(r for r in revenue if r.symbol == "1240")
    assert first.revenue_month == date(2026, 9, 1)
    assert first.revenue == Decimal(282821000)


def test_company_profiles_par_value_shares_and_industry() -> None:
    twse = TwseProvider(client=make_client(httpx.MockTransport(_mops_handler)))
    profiles = {
        p.symbol: p for p in twse.parse_company_profiles(twse.fetch_company_profiles("twse"))
    }
    assert profiles["1101"].par_value == Decimal(10)
    assert profiles["1101"].issued_shares == 7523181742
    assert profiles["1101"].industry_code == "01"
    tpex = TpexProvider(client=make_client(httpx.MockTransport(_mops_handler)))
    otc = {p.symbol: p for p in tpex.parse_company_profiles(tpex.fetch_company_profiles("tpex"))}
    assert otc["1240"].issued_shares == 46443992
    assert otc["1240"].market == "tpex"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("新台幣                 10.0000元", Decimal(10)),
        ("新台幣 1.0000元", Decimal(1)),
        ("美元 0.0100元", None),
        ("", None),
    ],
)
def test_par_value_only_in_twd(text: str, expected: Decimal | None) -> None:
    assert par_value(text) == expected
