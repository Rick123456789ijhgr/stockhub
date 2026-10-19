"""Portfolio math: hand-checked cases, plus the shared fixture the web tests also use."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import pytest

from stockhub.common.settings import PROJECT_ROOT
from stockhub.engine import portfolio as pf
from stockhub.engine.portfolio import Action, FeeSettings, Mark, Security, Trade

FIXTURE = PROJECT_ROOT / "testdata" / "portfolio.json"


def test_round_money_ignores_float_noise() -> None:
    assert 1.15 * 100 != 115  # 114.99999999999999, the noise this guards against
    assert pf.round_money(1.15 * 100) == 115
    assert pf.round_money(100_000 * 0.001425) == 142
    assert pf.round_money(100_000 * 0.001425, "round") == 143
    assert pf.round_money(19.999) == 19


def test_broker_fee_discount_minimum_and_rebate() -> None:
    plain = FeeSettings()
    assert pf.broker_fee(100_000, 1000, plain) == pf.Fee(142, 0)
    assert pf.broker_fee(10_000, 1000, plain) == pf.Fee(20, 0)  # 14.25 -> minimum 20
    assert pf.broker_fee(5_000, 500, plain) == pf.Fee(7, 0)  # odd lot, minimum 1
    discounted = FeeSettings(discount=0.28)
    assert pf.broker_fee(100_000, 1000, discounted) == pf.Fee(39, 0)  # 39.9
    rebate = FeeSettings(discount=0.28, discount_mode="rebate")
    assert pf.broker_fee(100_000, 1000, rebate) == pf.Fee(142, 103)
    assert pf.net_fee(100_000, 1000, rebate) == 39
    assert pf.broker_fee(10_000, 1000, rebate) == pf.Fee(20, 0)  # both at the minimum


def test_tax_rates_and_exceptions() -> None:
    assert pf.tax_rate("stock", "2330", "2026-10-19", False) == 0.003
    assert pf.tax_rate("stock", "2330", "2026-10-19", True) == 0.0015
    assert pf.tax_rate("stock", "2330", "2016-10-19", True) == 0.003  # before the cut
    assert pf.tax_rate("stock", "2330", "2028-01-03", True) == 0.003  # after it ends
    assert pf.tax_rate("etf", "0050", "2026-10-19", True) == 0.001
    assert pf.tax_rate("etf", "00679B", "2026-10-19", False) == 0.0
    assert pf.tax_rate("etf", "00679B", "2027-01-04", False) == 0.001
    assert pf.transaction_tax(60_000, 0.003) == 180


def test_average_cost_and_realized() -> None:
    trades = [
        Trade("1", "A", "2026-01-05", "buy", 1000, 100, fee=142),
        Trade("2", "A", "2026-02-02", "buy", 1000, 110, fee=156),
        Trade("3", "A", "2026-03-02", "sell", 500, 120, fee=85, tax=180),
    ]
    ledger = pf.replay(trades, [], as_of="2026-10-19")
    (p,) = ledger.positions
    assert p.shares == 1500
    # cost 210,298; selling a quarter takes out 52,574.5
    assert p.cost == pytest.approx(210_298 * 0.75)
    assert p.avg_cost == pytest.approx(210_298 / 2000)
    assert ledger.realized[0].pnl == pytest.approx(60_000 - 85 - 180 - 52_574.5)
    assert p.realized == ledger.realized[0].pnl


def test_selling_out_resets_cost_and_rebates_are_income() -> None:
    trades = [
        Trade("1", "A", "2026-01-05", "buy", 1000, 33.33, fee=142, rebate=100),
        Trade("2", "A", "2026-01-06", "sell", 1000, 40, fee=57, tax=120, rebate=40),
    ]
    (p,) = pf.replay(trades, [], as_of="2026-10-19").positions
    assert (p.shares, p.cost, p.avg_cost) == (0, 0.0, None)
    assert p.realized == pytest.approx(40_000 - 57 - 120 - 33_330 - 142)
    assert p.rebates == 140


def test_dividends_use_the_holding_before_the_ex_date() -> None:
    trades = [
        Trade("1", "A", "2026-06-01", "buy", 1500, 50, fee=0),
        Trade("2", "A", "2026-07-01", "buy", 1000, 50, fee=0),  # on the ex-date: not entitled
    ]
    actions = [
        Action("A", "2026-07-01", "cash_and_stock_dividend", 3.5, 0.05),
        Action("A", "2027-01-04", "cash_dividend", 1.0),  # after as_of: ignored
        Action("B", "2026-07-01", "cash_dividend", 9.0),  # never held
    ]
    ledger = pf.replay(trades, actions, as_of="2026-10-19")
    (d,) = ledger.dividends
    assert (d.shares_held, d.cash, d.stock_shares, d.shares_after) == (1500, 5250, 75, 1575)
    (p,) = ledger.positions
    assert p.shares == 2575
    assert p.cost == 125_000  # unchanged by the dividend
    assert p.dividends == 5250


def test_implied_ratios_from_reference_price() -> None:
    # Old TWSE 權息: only cash published; (100 - 2) / 93.33 - 1 = 0.05003 -> 0.05
    e = pf.entitlement(
        Action("A", "2005-07-01", "cash_and_stock_dividend", 2.0, None, None, 100, 93.33)
    )
    assert e == pf.Entitlement(2.0, 0.05, 1.0, True)
    # Plain cash dividend never infers a stock part.
    assert pf.entitlement(Action("A", "2005-07-01", "cash_dividend", 2.0, None, None, 100, 90)) == (
        pf.Entitlement(2.0, 0.0, 1.0, False)
    )
    # Capital reduction with a refund but no ratio: (50 - 3) / 78.33 = 0.6
    e = pf.entitlement(Action("A", "2012-01-02", "capital_reduction", 3.0, None, None, 50, 78.33))
    assert e == pf.Entitlement(3.0, 0.0, 0.6, True)
    assert pf.entitlement(Action("A", "2012-01-02", "rights_issue", 0.0)) is None
    assert pf.entitlement(Action("A", "2012-01-02", "split")) is None


def test_split_and_reduction_change_shares_not_cost() -> None:
    trades = [Trade("1", "A", "2026-01-05", "buy", 1001, 100)]
    actions = [
        Action("A", "2026-03-02", "capital_reduction", 2.0, ratio=0.6),
        Action("A", "2026-05-04", "split", ratio=4.0),
    ]
    ledger = pf.replay(trades, actions, as_of="2026-10-19")
    reduction, split = ledger.dividends
    assert (reduction.shares_after, reduction.cash) == (600, 2002)  # 600.6 -> 600 shares
    assert split.shares_after == 2400
    assert ledger.positions[0].cost == 100_100


def test_oversell_is_an_issue_and_skipped() -> None:
    trades = [
        Trade("1", "A", "2026-01-05", "buy", 1000, 100),
        Trade("2", "A", "2026-01-06", "sell", 1500, 100),
    ]
    ledger = pf.replay(trades, [], as_of="2026-10-19")
    assert ledger.issues == [pf.Issue("2", "A", "2026-01-06", 1000, 1500)]
    assert ledger.positions[0].shares == 1000
    assert ledger.realized == []


def test_same_day_round_trip_processes_buys_first() -> None:
    trades = [
        Trade("1", "A", "2026-01-05", "sell", 1000, 101, fee=0, tax=151),
        Trade("2", "A", "2026-01-05", "buy", 1000, 100, fee=0),
    ]
    ledger = pf.replay(trades, [], as_of="2026-10-19")
    assert ledger.issues == []
    assert ledger.realized[0].pnl == pytest.approx(1000 - 151)


def test_valuation_and_day_change() -> None:
    trades = [
        Trade("1", "A", "2026-10-01", "buy", 2000, 100, fee=285),
        Trade("2", "A", "2026-10-19", "buy", 1000, 104, fee=148),  # bought on the mark date
        Trade("3", "A", "2026-10-19", "sell", 500, 106, fee=75, tax=159),
    ]
    marks = {"A": Mark("2026-10-19", 105, 102)}
    secs = {"A": Security("stock", "2330")}
    (p,) = pf.replay(trades, [], as_of="2026-10-19", marks=marks, securities=secs).positions
    assert p.shares == 2500
    # held 2000 at 102 -> 105; bought 1000 at 104 -> 105; sold 500 at 106 (from 102 basis)
    assert p.day_change == pytest.approx(2500 * 105 - 2000 * 102 - 104_000 + 53_000)
    value = 2500 * 105
    est = pf.net_fee(value, 2500, FeeSettings()) + pf.transaction_tax(value, 0.003)
    assert p.market_value == value
    assert p.est_sell_cost == est
    assert p.unrealized == pytest.approx(value - p.cost - est)


def test_stale_mark_has_no_day_change() -> None:
    trades = [Trade("1", "A", "2026-10-19", "buy", 1000, 100)]
    (p,) = pf.replay(
        trades, [], as_of="2026-10-19", marks={"A": Mark("2026-10-16", 99, 98)}
    ).positions
    assert p.day_change is None
    assert p.market_value == 99_000


def _close(actual: Any, expected: Any, path: str) -> None:
    if isinstance(expected, dict):
        assert set(actual) == set(expected), path
        for key in expected:
            _close(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert len(actual) == len(expected), path
        for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
            _close(a, e, f"{path}[{i}]")
    elif isinstance(expected, float) and not isinstance(expected, bool):
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-9), path
    else:
        assert actual == expected, path


def test_matches_shared_fixture() -> None:
    """Python side of the shared fixture (web/src/lib/portfolio.test.ts is the other)."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for i, case in enumerate(data["fees"]):
        fee = pf.broker_fee(case["amount"], case["quantity"], FeeSettings(**case["settings"]))
        assert asdict(fee) == case["expected"], f"fees[{i}]"
    for i, case in enumerate(data["tax"]):
        rate = pf.tax_rate(case["type"], case["symbol"], case["date"], case["day_trade"])
        assert rate == case["expected"]["rate"], f"tax[{i}]"
        assert pf.transaction_tax(case["amount"], rate) == case["expected"]["tax"], f"tax[{i}]"
    for case in data["replay"]:
        ledger = pf.replay(
            [Trade(**t) for t in case["trades"]],
            [Action(**a) for a in case["actions"]],
            as_of=case["as_of"],
            marks={k: Mark(**m) for k, m in case["marks"].items()},
            securities={k: Security(**s) for k, s in case["securities"].items()},
            fees=FeeSettings(**case["fees"]),
        )
        actual = {"ledger": asdict(ledger), "totals": asdict(pf.totals(ledger.positions))}
        _close(actual, case["expected"], case["name"])
