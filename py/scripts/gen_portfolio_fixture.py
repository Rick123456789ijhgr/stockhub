"""Regenerate testdata/portfolio.json, the shared fixture for the Python and TS portfolio math.

Run from py/: uv run python scripts/gen_portfolio_fixture.py
Hand-written scenarios cover each rule (dividends, implied ratios, splits, oversells, stale
marks, rebates); a seeded pseudo-random ledger covers the arithmetic at volume. Expected
values come from stockhub.engine.portfolio.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from stockhub.engine import portfolio as pf
from stockhub.engine.portfolio import (
    Action,
    FeeSettings,
    Mark,
    Preview,
    Receipt,
    Security,
    Trade,
)

OUT = Path(__file__).resolve().parents[2] / "testdata" / "portfolio.json"

SETTINGS = [
    FeeSettings(),
    FeeSettings(discount=0.28, min_fee=20, min_fee_odd_lot=1),
    FeeSettings(discount=0.6, discount_mode="rebate"),
    FeeSettings(discount=0.38, rounding="round", min_fee_odd_lot=20),
]


def fee_cases() -> list[dict[str, Any]]:
    cases = []
    amounts = [
        (100_000, 1000),
        (14_035.5, 1000),
        (5_000, 500),
        (33_330, 1000),
        (1, 1),
        (2_515.5, 50),
        (1_234_567.8, 3000),
        (7_017.5, 999),
        (350_877.19, 1000),
    ]
    for s in SETTINGS:
        for amount, quantity in amounts:
            fee = pf.broker_fee(amount, quantity, s)
            cases.append(
                {
                    "settings": asdict(s),
                    "amount": amount,
                    "quantity": quantity,
                    "expected": asdict(fee),
                }
            )
    return cases


def tax_cases() -> list[dict[str, Any]]:
    rows = [
        ("stock", "2330", "2026-10-19", False, 1_050_000),
        ("stock", "2330", "2026-10-19", True, 1_050_000),
        ("stock", "2330", "2017-04-27", True, 33_333),
        ("stock", "2330", "2027-12-31", True, 33_333),
        ("stock", "2330", "2028-01-03", True, 33_333),
        ("etf", "0050", "2026-10-19", True, 99_999),
        ("etf", "00679B", "2016-12-30", False, 99_999),
        ("etf", "00679B", "2026-12-31", False, 99_999),
        ("etf", "00679B", "2027-01-04", False, 99_999),
        ("etf", "00632R", "2026-10-19", False, 12_345.67),
    ]
    out = []
    for kind, symbol, day, day_trade, amount in rows:
        rate = pf.tax_rate(kind, symbol, day, day_trade)
        out.append(
            {
                "type": kind,
                "symbol": symbol,
                "date": day,
                "day_trade": day_trade,
                "amount": amount,
                "expected": {"rate": rate, "tax": pf.transaction_tax(amount, rate)},
            }
        )
    return out


def trade(
    tid: str,
    stock: str,
    day: str,
    side: str,
    qty: int,
    price: float,
    sec: Security,
    s: FeeSettings,
    day_trade: bool = False,
) -> Trade:
    amount = qty * price
    fee = pf.broker_fee(amount, qty, s)
    tax = (
        pf.transaction_tax(amount, pf.tax_rate(sec.type, sec.symbol, day, day_trade))
        if side == "sell"
        else 0
    )
    return Trade(tid, stock, day, side, qty, price, fee.fee, tax, fee.rebate, day_trade)  # type: ignore[arg-type]


def scenario_basic() -> dict[str, Any]:
    s = SETTINGS[1]
    secs = {"1": Security("stock", "2330"), "2": Security("etf", "0056")}
    trades = [
        trade("1", "1", "2026-03-02", "buy", 1000, 812.0, secs["1"], s),
        trade("2", "2", "2026-03-03", "buy", 5000, 36.71, secs["2"], s),
        trade("3", "1", "2026-05-04", "buy", 300, 905.5, secs["1"], s),
        trade("4", "1", "2026-06-11", "sell", 400, 1010.0, secs["1"], s),
        trade("5", "2", "2026-07-16", "buy", 1000, 35.2, secs["2"], s),
        trade("6", "1", "2026-10-19", "sell", 100, 1460.0, secs["1"], s, day_trade=False),
        trade("7", "1", "2026-10-19", "buy", 100, 1450.0, secs["1"], s),
        # fully matched day trade
        trade("8", "1", "2026-08-03", "buy", 1000, 1100.0, secs["1"], s, day_trade=True),
        trade("9", "1", "2026-08-03", "sell", 1000, 1110.0, secs["1"], s, day_trade=True),
        # partly matched: 1,000 of the 2,000 bought stay in the inventory
        trade("10", "1", "2026-09-01", "buy", 2000, 1200.0, secs["1"], s, day_trade=True),
        trade("11", "1", "2026-09-01", "sell", 600, 1210.0, secs["1"], s, day_trade=True),
        trade("12", "1", "2026-09-01", "sell", 400, 1215.0, secs["1"], s, day_trade=True),
        # flagged but nothing to match: an ordinary sell
        trade("13", "1", "2026-09-02", "sell", 500, 1215.0, secs["1"], s, day_trade=True),
        # day-trade sell larger than the day's day-trade buys plus the holding
        trade("14", "2", "2026-09-03", "buy", 100, 36.0, secs["2"], s, day_trade=True),
        trade("15", "2", "2026-09-03", "sell", 9000, 36.1, secs["2"], s, day_trade=True),
    ]
    actions = [
        Action("1", "2026-03-19", "cash_dividend", 4.5, None, None, 905.0, 900.5),
        Action("1", "2026-06-12", "cash_dividend", 5.0, None, None, 1010.0, 1005.0),
        Action("2", "2026-04-23", "cash_dividend", 0.866, None, None, 37.0, 36.13),
        Action(
            "2", "2026-07-16", "cash_dividend", 0.8, None, None, 36.0, 35.2
        ),  # bought on ex-date
        Action("2", "2026-10-21", "cash_dividend", 1.0),  # after as_of
    ]
    marks = {"1": Mark("2026-10-19", 1455.0, 1440.0), "2": Mark("2026-10-19", 37.15, 37.4)}
    previews = [
        Preview("1", "2026-10-19", "cash_dividend", 5.0),  # today, not in the official table yet
        Preview("2", "2026-10-22", "cash_dividend", None),  # amount not announced
        Preview("2", "2026-11-18", "cash_dividend", 1.2),
        Preview("1", "2026-12-17", "cash_and_stock_dividend", 6.0, 0.02),
        Preview("9", "2026-12-17", "cash_dividend", 1.0),  # not held
    ]
    receipts = {pf.receipt_key("2", "2026-04-23", "cash_dividend"): Receipt(4320.0)}
    return {
        "name": "basic",
        "previews": previews,
        "receipts": receipts,
        "trades": trades,
        "actions": actions,
        "as_of": "2026-10-19",
        "marks": marks,
        "securities": secs,
        "fees": s,
    }


def scenario_events() -> dict[str, Any]:
    s = SETTINGS[2]
    secs = {
        "10": Security("stock", "1101"),
        "11": Security("etf", "00679B"),
        "12": Security("stock", "8932"),
        "13": Security("etf", "0050"),
    }
    trades = [
        trade("1", "10", "2005-06-01", "buy", 2345, 21.35, secs["10"], s),
        trade("2", "11", "2024-01-02", "buy", 3000, 30.12, secs["11"], s),
        trade("3", "12", "2011-01-03", "buy", 1500, 18.4, secs["12"], s),
        trade("4", "13", "2025-06-10", "buy", 250, 190.0, secs["13"], s),
        trade(
            "5", "12", "2012-01-03", "sell", 2000, 12.0, secs["12"], s
        ),  # oversold after reduction
        trade("6", "11", "2024-06-03", "sell", 1000, 29.5, secs["11"], s),
        trade("7", "10", "2005-08-01", "sell", 2462, 24.0, secs["10"], s),  # sells out
        trade("8", "13", "2025-06-20", "sell", 1000, 48.0, secs["13"], s),
    ]
    actions = [
        Action("10", "2005-07-04", "cash_and_stock_dividend", 2.0, None, None, 25.0, 21.9),
        Action("11", "2024-04-16", "cash_dividend", 0.41, None, None, 30.0, 29.59),
        Action("12", "2011-08-01", "capital_reduction", 0.0, None, None, 16.0, 26.67),
        Action("13", "2025-06-18", "split", None, None, 4.0, 188.65, 47.16),
        Action("13", "2025-07-17", "cash_dividend", 0.47, None, None, 49.0, 48.53),
        Action("13", "2025-08-01", "rights_issue", 0.0),
    ]
    receipts = {
        pf.receipt_key("10", "2005-07-04", "cash_and_stock_dividend"): Receipt(None, 118),
        pf.receipt_key("11", "2024-04-16", "cash_dividend"): Receipt(1220.0, None),
    }
    marks = {
        "10": Mark("2026-10-19", 30.0, 29.0),
        "11": Mark("2026-10-16", 28.66, 28.7),
        "12": Mark("2026-10-19", 10.0, None),
        "13": Mark("2025-06-19", 47.5, 47.0),
    }
    return {
        "name": "events",
        "previews": [],
        "receipts": receipts,
        "trades": trades,
        "actions": actions,
        "as_of": "2026-10-19",
        "marks": marks,
        "securities": secs,
        "fees": s,
    }


def scenario_random() -> dict[str, Any]:
    rng = random.Random(20261019)  # noqa: S311 - fixture data, not crypto
    s = SETTINGS[3]
    secs = {
        "21": Security("stock", "2317"),
        "22": Security("etf", "006208"),
        "23": Security("stock", "6488"),
    }
    prices = {"21": 100.0, "22": 80.0, "23": 400.0}
    held = {k: 0 for k in secs}
    trades: list[Trade] = []
    actions: list[Action] = []
    day = date(2023, 1, 2)
    for _ in range(260):
        day += timedelta(days=1 if day.weekday() < 4 else 3)
        iso = day.isoformat()
        for k in secs:
            prices[k] = round(max(5.0, prices[k] * (1 + rng.uniform(-0.03, 0.03))), 2)
        if rng.random() < 0.06:
            k = rng.choice(list(secs))
            cash = round(rng.uniform(0.5, 5), 2)
            ratio = rng.choice([None, 0.0, 0.03, 0.1])
            kind = "cash_dividend" if not ratio else "cash_and_stock_dividend"
            actions.append(
                Action(
                    k,
                    iso,
                    kind,
                    cash,
                    ratio,
                    None,
                    prices[k],
                    round((prices[k] - cash) / (1 + (ratio or 0)), 2),
                )
            )
        if rng.random() < 0.1:
            k = rng.choice(list(secs))
            qty = rng.choice([1000, 2000, rng.randint(1, 999)])
            out_qty = rng.choice([qty, max(1, qty // 2)])
            for side, q, px in (("buy", qty, prices[k]), ("sell", out_qty, prices[k] * 1.01)):
                trades.append(
                    trade(str(len(trades) + 1), k, iso, side, q, round(px, 2), secs[k], s, True)
                )
            held[k] += qty - out_qty
        if rng.random() < 0.5:
            k = rng.choice(list(secs))
            sell = held[k] > 0 and rng.random() < 0.4
            if sell:
                qty = rng.choice([held[k], max(1, held[k] // 2), rng.randint(1, held[k])])
            else:
                qty = rng.choice([1000, 2000, rng.randint(1, 999)])
            side = "sell" if sell else "buy"
            trades.append(
                trade(
                    str(len(trades) + 1),
                    k,
                    iso,
                    side,
                    qty,
                    prices[k],
                    secs[k],
                    s,
                    day_trade=sell and rng.random() < 0.2,
                )
            )
            held[k] += -qty if sell else qty
    last = day.isoformat()
    marks = {k: Mark(last, prices[k], round(prices[k] * 0.99, 2)) for k in secs}
    return {
        "name": "random",
        "previews": [Preview(k, "2099-01-02", "cash_dividend", 1.5) for k in secs],
        "receipts": {},
        "trades": trades,
        "actions": actions,
        "as_of": last,
        "marks": marks,
        "securities": secs,
        "fees": s,
    }


def nhi_cases() -> list[dict[str, Any]]:
    rows = [
        (19_999, 0, "2026-07-01"),
        (20_000, 0, "2026-07-01"),
        (15_000, 600, "2026-07-01"),  # 15,000 + 600 shares at par 10 = 21,000
        (123_456, 0, "2018-08-01"),
        (4_999, 0, "2014-08-01"),
        (5_000, 0, "2014-08-01"),
        (50_000, 0, "2012-08-01"),
        (12_000_000, 0, "2026-07-01"),  # capped at 10 million
    ]
    return [
        {"cash": c, "stock_shares": n, "ex_date": d, "expected": pf.nhi_premium(c, n, d)}
        for c, n, d in rows
    ]


def replay_case(sc: dict[str, Any]) -> dict[str, Any]:
    actions = pf.with_previews(sc["actions"], sc["previews"], sc["as_of"])
    ledger = pf.replay(
        sc["trades"],
        actions,
        as_of=sc["as_of"],
        marks=sc["marks"],
        securities=sc["securities"],
        fees=sc["fees"],
        receipts=sc["receipts"],
    )
    coming = pf.upcoming(ledger.positions, sc["previews"], sc["as_of"])
    return {
        "name": sc["name"],
        "trades": [asdict(t) for t in sc["trades"]],
        "actions": [asdict(a) for a in sc["actions"]],
        "as_of": sc["as_of"],
        "marks": {k: asdict(m) for k, m in sc["marks"].items()},
        "securities": {k: asdict(v) for k, v in sc["securities"].items()},
        "fees": asdict(sc["fees"]),
        "previews": [asdict(v) for v in sc["previews"]],
        "receipts": {k: asdict(r) for k, r in sc["receipts"].items()},
        "expected": {
            "ledger": asdict(ledger),
            "totals": asdict(pf.totals(ledger.positions)),
            "upcoming": [asdict(u) for u in coming],
        },
    }


def main() -> None:
    data = {
        "comment": "Generated by py/scripts/gen_portfolio_fixture.py; do not edit by hand.",
        "fees": fee_cases(),
        "tax": tax_cases(),
        "nhi": nhi_cases(),
        "replay": [
            replay_case(sc) for sc in (scenario_basic(), scenario_events(), scenario_random())
        ],
    }
    OUT.parent.mkdir(exist_ok=True)
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
