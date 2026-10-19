"""Portfolio math, mirrored exactly by web/src/lib/portfolio.ts (CLAUDE.md rule 11).

Both implementations evaluate the same expressions in the same order on IEEE doubles and
are tested against testdata/portfolio.json (py/scripts/gen_portfolio_fixture.py). Change
one, change the other, regenerate the fixture.

Conventions (decided in M2, see docs/DECISIONS.md D-067..):
- Quantities are shares. Dates are ISO strings ("YYYY-MM-DD"), compared as strings.
- Whole-dollar amounts (fees, tax, dividends) are rounded with `round_money`, which adds
  EPS first so 142.49999999999997 (float noise for 142.5) behaves like 142.5.
- Average cost: a buy adds quantity * price + fee to the total cost; a sell takes out
  cost * quantity / shares (all of it when selling out); realized P&L = proceeds - fee -
  tax - cost taken out. Fee rebates are counted as separate income.
- Corporate actions never change the total cost (cash goes to dividend income, stock
  dividends / splits / reductions only change the share count). Entitlement is the
  holding before the ex-date, i.e. after every trade dated before it.
- Within one day: corporate actions first, then buys, then sells (so a same-day round
  trip never goes short), each in input order.
- A sell larger than the holding is reported as an issue and left out of the replay.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

EPS = 1e-6

Rounding = Literal["floor", "round"]
DiscountMode = Literal["instant", "rebate"]


def round_money(value: float, rounding: Rounding = "floor") -> int:
    """Whole TWD: floor (元以下捨去) or half-up rounding, robust to float noise."""
    if rounding == "round":
        return math.floor(value + 0.5 + EPS)
    return math.floor(value + EPS)


def round_to(value: float, digits: int) -> float:
    """Half-up rounding to `digits` decimals (same result as the TS port)."""
    scale = float(10**digits)
    return math.floor(value * scale + 0.5) / scale


# --- fees and tax -------------------------------------------------------------------------


@dataclass(frozen=True)
class FeeSettings:
    rate: float = 0.001425
    discount: float = 1.0  # multiplier: 0.28 = 2.8 折, 1 = none
    min_fee: int = 20
    min_fee_odd_lot: int = 1  # orders of fewer than 1,000 shares
    discount_mode: DiscountMode = "instant"
    rounding: Rounding = "floor"


@dataclass(frozen=True)
class Fee:
    fee: int  # charged on the trade
    rebate: int  # refunded later (rebate mode), else 0


def broker_fee(amount: float, quantity: int, s: FeeSettings) -> Fee:
    """Fee for a trade worth `amount`. Instant: the discounted fee is charged. Rebate: the
    full fee is charged and the difference to the discounted fee comes back later."""
    minimum = s.min_fee_odd_lot if quantity < 1000 else s.min_fee
    base = amount * s.rate
    full = max(minimum, round_money(base, s.rounding))
    discounted = max(minimum, round_money(base * s.discount, s.rounding))
    if s.discount_mode == "instant":
        return Fee(discounted, 0)
    return Fee(full, max(0, full - discounted))


def net_fee(amount: float, quantity: int, s: FeeSettings) -> int:
    """What a trade finally costs in fees (after any rebate)."""
    f = broker_fee(amount, quantity, s)
    return f.fee - f.rebate


BOND_ETF_EXEMPT = ("2017-01-01", "2026-12-31")
DAY_TRADE_HALF = ("2017-04-28", "2027-12-31")


def tax_rate(security_type: str, symbol: str, trade_date: str, day_trade: bool) -> float:
    """Securities transaction tax on sells: stocks 0.3% (day trades 0.15% while the cut
    runs), ETFs 0.1%, bond ETFs (symbol ending in B) exempt while the exemption runs."""
    if security_type == "etf":
        exempt = BOND_ETF_EXEMPT[0] <= trade_date <= BOND_ETF_EXEMPT[1]
        if symbol.endswith("B") and exempt:
            return 0.0
        return 0.001
    if day_trade and DAY_TRADE_HALF[0] <= trade_date <= DAY_TRADE_HALF[1]:
        return 0.0015
    return 0.003


def transaction_tax(amount: float, rate: float) -> int:
    return round_money(amount * rate)


# --- ledger replay ------------------------------------------------------------------------


@dataclass(frozen=True)
class Trade:
    id: str
    stock: str
    date: str
    side: Literal["buy", "sell"]
    quantity: int
    price: float
    fee: float = 0.0
    tax: float = 0.0
    rebate: float = 0.0


@dataclass(frozen=True)
class Action:
    """A corporate_actions row (TWD per share; ratios as stored)."""

    stock: str
    ex_date: str
    action_type: str
    cash_dividend: float | None = None
    stock_dividend_ratio: float | None = None
    ratio: float | None = None
    prev_close: float | None = None
    reference_price: float | None = None


@dataclass(frozen=True)
class Mark:
    """Latest price of a stock: an intraday quote or the last daily close. `prev_close` is
    on the same share basis (the exchange reference price on an ex-date)."""

    date: str
    price: float
    prev_close: float | None


@dataclass(frozen=True)
class Security:
    type: str
    symbol: str


@dataclass(frozen=True)
class Entitlement:
    cash_per_share: float
    stock_ratio: float  # new shares per share held (stock dividends)
    share_ratio: float  # shares after / before (splits, reductions); 1 for dividends
    implied: bool  # a ratio was inferred from the exchange's reference price


DIVIDEND_TYPES = ("cash_dividend", "stock_dividend", "cash_and_stock_dividend")
SHARE_TYPES = ("split", "reverse_split", "capital_reduction")


def entitlement(a: Action) -> Entitlement | None:
    """What one share before the ex-date turns into. None for events with no automatic
    effect on a holder (rights issues must be subscribed, `other` is unknown).

    Missing parts are inferred from the reference price: stock dividend ratio =
    (prev - cash) / ref - 1 (old TWSE 權息 rows only publish the cash part) and share
    ratio = (prev - refund) / ref. Both are rounded and flagged as implied."""
    prev = a.prev_close or 0.0
    ref = a.reference_price or 0.0
    usable = prev > 0 and ref > 0
    cash = a.cash_dividend if a.cash_dividend is not None else 0.0
    if a.action_type in DIVIDEND_TYPES:
        if a.stock_dividend_ratio is not None:
            return Entitlement(cash, a.stock_dividend_ratio, 1.0, False)
        if a.action_type == "cash_dividend" or not usable:
            return Entitlement(cash, 0.0, 1.0, False)
        implied = round_to((prev - cash) / ref - 1, 3)
        return Entitlement(cash, max(0.0, implied), 1.0, True)
    if a.action_type in SHARE_TYPES:
        if a.ratio is not None:
            return Entitlement(cash, 0.0, a.ratio, False)
        if not usable:
            return None
        return Entitlement(cash, 0.0, round_to((prev - cash) / ref, 3), True)
    return None


@dataclass
class DividendEntry:
    stock: str
    ex_date: str
    action_type: str
    shares_held: int
    cash_per_share: float
    cash: int
    stock_ratio: float
    stock_shares: int
    share_ratio: float
    shares_after: int
    implied: bool


@dataclass
class RealizedEntry:
    id: str
    stock: str
    date: str
    quantity: int
    proceeds: float
    cost: float
    fee: float
    tax: float
    pnl: float


@dataclass
class Issue:
    id: str
    stock: str
    date: str
    held: int
    quantity: int


@dataclass
class Position:
    stock: str
    shares: int = 0
    cost: float = 0.0
    realized: float = 0.0
    dividends: float = 0.0
    rebates: float = 0.0
    avg_cost: float | None = None
    mark_date: str | None = None
    price: float | None = None
    market_value: float | None = None
    est_sell_cost: float | None = None
    unrealized: float | None = None
    day_change: float | None = None


@dataclass
class Ledger:
    positions: list[Position] = field(default_factory=list)
    realized: list[RealizedEntry] = field(default_factory=list)
    dividends: list[DividendEntry] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


@dataclass
class _Day:
    actions: list[Action] = field(default_factory=list)
    buys: list[Trade] = field(default_factory=list)
    sells: list[Trade] = field(default_factory=list)


def replay(
    trades: Sequence[Trade],
    actions: Iterable[Action],
    *,
    as_of: str,
    marks: dict[str, Mark] | None = None,
    securities: dict[str, Security] | None = None,
    fees: FeeSettings | None = None,
) -> Ledger:
    """Replay trades (in id order) and corporate actions up to `as_of`, then value the open
    positions at `marks`. Positions are sorted by stock key; actions on stocks that were
    never traded are ignored."""
    marks = marks or {}
    securities = securities or {}
    fee_settings = fees or FeeSettings()
    days: dict[str, dict[str, _Day]] = {}
    for t in trades:
        day = days.setdefault(t.stock, {}).setdefault(t.date, _Day())
        (day.buys if t.side == "buy" else day.sells).append(t)
    for a in actions:
        if a.stock in days and a.ex_date <= as_of:
            days[a.stock].setdefault(a.ex_date, _Day()).actions.append(a)

    out = Ledger()
    for stock in sorted(days):
        p = Position(stock)
        mark = marks.get(stock)
        base: int | None = None
        mark_buys = 0.0
        mark_sells = 0.0
        stale = False
        for date in sorted(days[stock]):
            day = days[stock][date]
            if mark is not None and date > mark.date:
                if base is None:
                    base = p.shares
                stale = True
            for a in day.actions:
                _apply_action(p, a, out)
            if mark is not None and date == mark.date:
                base = p.shares
            for t in day.buys:
                p.shares += t.quantity
                p.cost += t.quantity * t.price + t.fee
                p.rebates += t.rebate
                if mark is not None and date == mark.date:
                    mark_buys += t.quantity * t.price
            for t in day.sells:
                if t.quantity > p.shares:
                    out.issues.append(Issue(t.id, stock, date, p.shares, t.quantity))
                    continue
                cost_out = p.cost if t.quantity == p.shares else p.cost * t.quantity / p.shares
                proceeds = t.quantity * t.price
                pnl = proceeds - t.fee - t.tax - cost_out
                out.realized.append(
                    RealizedEntry(
                        t.id, stock, date, t.quantity, proceeds, cost_out, t.fee, t.tax, pnl
                    )
                )
                p.realized += pnl
                p.rebates += t.rebate
                p.shares -= t.quantity
                p.cost = 0.0 if p.shares == 0 else p.cost - cost_out
                if mark is not None and date == mark.date:
                    mark_sells += proceeds
        if base is None:
            base = p.shares
        _value(p, mark, securities.get(stock), fee_settings, as_of)
        moved = p.shares > 0 or base > 0
        if mark is not None and mark.prev_close is not None and not stale and moved:
            p.day_change = p.shares * mark.price - base * mark.prev_close - mark_buys + mark_sells
        out.positions.append(p)
    return out


def _apply_action(p: Position, a: Action, out: Ledger) -> None:
    held = p.shares
    if held <= 0:
        return
    e = entitlement(a)
    if e is None:
        return
    cash = round_money(held * e.cash_per_share)
    stock_shares = round_money(held * e.stock_ratio)
    after = held if e.share_ratio == 1.0 else round_money(held * e.share_ratio)
    p.shares = after + stock_shares
    p.dividends += cash
    if p.shares == 0:
        p.realized -= p.cost
        p.cost = 0.0
    out.dividends.append(
        DividendEntry(
            p.stock,
            a.ex_date,
            a.action_type,
            held,
            e.cash_per_share,
            cash,
            e.stock_ratio,
            stock_shares,
            e.share_ratio,
            p.shares,
            e.implied,
        )
    )


def _value(
    p: Position, mark: Mark | None, sec: Security | None, fees: FeeSettings, as_of: str
) -> None:
    if p.shares > 0:
        p.avg_cost = p.cost / p.shares
    if mark is None:
        return
    p.mark_date = mark.date
    p.price = mark.price
    if p.shares <= 0:
        return
    value = p.shares * mark.price
    rate = tax_rate(sec.type, sec.symbol, as_of, False) if sec else 0.003
    est = net_fee(value, p.shares, fees) + transaction_tax(value, rate)
    p.market_value = value
    p.est_sell_cost = float(est)
    p.unrealized = value - p.cost - est


@dataclass
class Totals:
    cost: float = 0.0
    market_value: float = 0.0
    unrealized: float = 0.0
    realized: float = 0.0
    dividends: float = 0.0
    rebates: float = 0.0
    day_change: float = 0.0


def totals(positions: Iterable[Position]) -> Totals:
    """Sums over positions; open positions without a mark add only their cost."""
    t = Totals()
    for p in positions:
        t.cost += p.cost
        t.market_value += p.market_value or 0.0
        t.unrealized += p.unrealized or 0.0
        t.realized += p.realized
        t.dividends += p.dividends
        t.rebates += p.rebates
        t.day_change += p.day_change or 0.0
    return t
