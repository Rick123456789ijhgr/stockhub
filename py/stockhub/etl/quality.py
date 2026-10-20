"""Data quality checks. Rows that fail go to quarantine tables, never to the main tables."""

from __future__ import annotations

from decimal import Decimal

from stockhub.engine.adjustments import implied_reference_price
from stockhub.etl.providers.base import (
    CorporateAction,
    DailyBar,
    DistributionLevel,
    DividendDetail,
    ForeignHolding,
    InstitutionalTrade,
    MarginBalance,
)

FACTOR_RANGE = (Decimal("0.02"), Decimal(50))
"""Per-event price factors outside this range are almost certainly parsing or source errors
(the largest real ones are 1:10 par-value changes and deep loss-offsetting reductions)."""


def check_daily_bar(bar: DailyBar) -> list[str]:
    """Names of failed checks; empty means the bar may be stored."""
    prices = (bar.open, bar.high, bar.low, bar.close)
    present = [p for p in prices if p is not None]
    if not present:
        # No regular-session trade. Volume can still be non-zero from after-hours or block
        # trades (seen on TWSE, e.g. 2321 on 2026-10-16), so this is normal, not an anomaly.
        return []
    reasons: list[str] = []
    if len(present) != len(prices):
        reasons.append("partial_ohlc")
    if any(p <= 0 for p in present):
        reasons.append("non_positive_price")
    if bar.high is not None and bar.low is not None:
        if bar.high < bar.low:
            reasons.append("high_below_low")
        else:
            for label, value in (("open", bar.open), ("close", bar.close)):
                if value is not None and not bar.low <= value <= bar.high:
                    reasons.append(f"{label}_outside_range")
    if bar.volume == 0 and len(present) == len(prices):
        reasons.append("prices_without_volume")
    return reasons


def check_corporate_action(action: CorporateAction) -> list[str]:
    """Names of failed checks; empty means the event may adjust prices."""
    prices = [p for p in (action.prev_close, action.reference_price) if p is not None]
    if any(p <= 0 for p in prices):
        return ["non_positive_price"]
    if action.prev_close is None or action.reference_price is None:
        if action.ratio is None:
            return ["no_reference_price"]
        factor = 1 / action.ratio
    else:
        factor = action.reference_price / action.prev_close
    reasons: list[str] = []
    low, high = FACTOR_RANGE
    if not low <= factor <= high:
        reasons.append("factor_out_of_range")
    if action.action_type == "cash_dividend" and factor > 1:
        # Paying cash never raises the reference price. 除權 can: it may include a cash
        # capital increase subscribed above the market price.
        reasons.append("dividend_raises_price")
    return reasons


REFERENCE_TOLERANCE = Decimal("0.005")
"""Parts that are right reproduce the published reference price to within its rounding to a
tick (at most ~0.2% on low prices); 0.5% leaves room without letting wrong parts through."""


def check_dividend_detail(
    detail: DividendDetail, prev_close: Decimal | None, reference_price: Decimal | None
) -> list[str]:
    """Names of failed checks for an event's cash / stock / rights parts."""
    if prev_close is None or reference_price is None or reference_price <= 0:
        return []  # nothing to compare with; the parts stand on their own
    if detail.rights_ratio > 0 and detail.subscription_price is None:
        return ["rights_without_price"]
    implied = implied_reference_price(
        prev_close,
        detail.cash_dividend,
        detail.stock_dividend_ratio,
        detail.rights_ratio,
        detail.subscription_price,
    )
    if abs(implied / reference_price - 1) > REFERENCE_TOLERANCE:
        return ["parts_do_not_match_reference"]
    return []


BALANCE_TOLERANCE = Decimal("0.005")
"""Assets vs liabilities + equity: filings balance exactly; 0.5% absorbs rounding to
thousands and sources that leave out a small equity line."""
QUARTER_REVENUE_TOLERANCE = Decimal("0.03")
YTD_MATCH_TOLERANCE = Decimal("0.01")


def check_statement(
    statement: str,
    basis: str,
    values: dict[str, Decimal],
    month_revenue: tuple[Decimal, Decimal] | None = None,
) -> list[str]:
    """Names of failed checks for one statement of one period (canonical item codes).

    `month_revenue` is (sum of the quarter's three months, sum of the year so far up to the
    quarter end) when every month is known. A single-quarter revenue far from the quarter's
    months but equal to the year so far is a year-to-date figure mislabeled as a quarter
    (seen at FinMind for the latest quarter, before its single-quarter derivation catches up).
    """
    reasons: list[str] = []
    if statement == "BS":
        assets = values.get("TotalAssets")
        liabilities = values.get("TotalLiabilities")
        equity = values.get("TotalEquity")
        if assets is not None and liabilities is not None and equity is not None:
            if assets <= 0:
                reasons.append("non_positive_assets")
            elif abs(assets - liabilities - equity) > assets * BALANCE_TOLERANCE:
                reasons.append("unbalanced")
    if statement == "IS":
        revenue = values.get("Revenue")
        if revenue is not None and revenue < 0:
            reasons.append("negative_revenue")
        if (
            basis == "quarter"
            and revenue is not None
            and month_revenue is not None
            and month_revenue[0] > 0
            and month_revenue[1] > month_revenue[0]  # not Q1, where the two are equal
        ):
            quarter, ytd = month_revenue
            off_quarter = abs(revenue / quarter - 1) > QUARTER_REVENUE_TOLERANCE
            if off_quarter and abs(revenue / ytd - 1) <= YTD_MATCH_TOLERANCE:
                reasons.append("ytd_as_quarter")
    return reasons


LIABILITY_ITEMS = frozenset(
    {
        "TotalLiabilities",
        "CurrentLiabilities",
        "NoncurrentLiabilities",
        "ShortTermBorrowings",
        "LongTermBorrowings",
        "BondsPayable",
    }
)


def suspect_liabilities(values: dict[str, Decimal]) -> bool:
    """An unbalanced balance sheet whose asset side (current + non-current = total) and
    equity side (parent + non-controlling = total) both add up: the liability figures are
    the wrong ones (seen at FinMind, e.g. current and non-current liabilities duplicated)."""
    assets = values.get("TotalAssets")
    parts = [
        values.get(k) for k in ("CurrentAssets", "NoncurrentAssets", "EquityParent", "TotalEquity")
    ]
    if assets is None or assets <= 0 or any(p is None for p in parts):
        return False
    current, noncurrent, parent, equity = (p for p in parts if p is not None)
    nci = values.get("EquityNCI") or Decimal(0)
    tolerance = assets * BALANCE_TOLERANCE
    return (
        abs(current + noncurrent - assets) <= tolerance and abs(parent + nci - equity) <= tolerance
    )


# ----------------------------------------------------------------------------- chips


def check_institutional_trade(trade: InstitutionalTrade) -> list[str]:
    """Each group's buy - sell is its net, and the groups add up to the exchange's total
    (foreign dealers are already inside dealers, so they are not added again)."""
    reasons: list[str] = []
    groups = [
        ("foreign", trade.foreign_buy, trade.foreign_sell, trade.foreign_net),
        ("trust", trade.trust_buy, trade.trust_sell, trade.trust_net),
        ("dealer", trade.dealer_buy, trade.dealer_sell, trade.dealer_net),
        (
            "foreign_dealer",
            trade.foreign_dealer_buy,
            trade.foreign_dealer_sell,
            trade.foreign_dealer_net,
        ),
    ]
    for name, buy, sell, net in groups:
        if buy is not None and sell is not None and net is not None and buy - sell != net:
            reasons.append(f"{name}_net_mismatch")
    self_net, hedge_net = trade.dealer_self_net, trade.dealer_hedge_net
    if self_net is not None and hedge_net is not None and self_net + hedge_net != trade.dealer_net:
        reasons.append("dealer_parts_mismatch")
    if trade.foreign_net + trade.trust_net + trade.dealer_net != trade.total_net:
        reasons.append("total_mismatch")
    return reasons


def check_margin_balance(row: MarginBalance) -> list[str]:
    """Today's balances follow from yesterday's and the day's flows (exact in every table
    checked, 2012 and 2026, both exchanges)."""
    reasons: list[str] = []
    if row.margin_prev + row.margin_buy - row.margin_sell - row.margin_redeem != (
        row.margin_balance
    ):
        reasons.append("margin_balance_mismatch")
    if row.short_prev + row.short_sell - row.short_cover - row.short_redeem != row.short_balance:
        reasons.append("short_balance_mismatch")
    return reasons


RATIO_TOLERANCE = Decimal("0.0002")
"""Published ratios are truncated to 0.01%, so held / issued may differ by that much."""


def check_foreign_holding(row: ForeignHolding) -> list[str]:
    reasons: list[str] = []
    if not Decimal(0) <= row.foreign_ratio <= Decimal(1):
        reasons.append("ratio_out_of_range")
    if row.limit_ratio is not None and not Decimal(0) <= row.limit_ratio <= Decimal(1):
        reasons.append("limit_out_of_range")
    if row.issued_shares > 0:
        implied = Decimal(row.foreign_shares) / Decimal(row.issued_shares)
        if abs(implied - row.foreign_ratio) > RATIO_TOLERANCE:
            reasons.append("ratio_mismatch")
    return reasons


def check_distribution(levels: list[DistributionLevel]) -> list[str]:
    """One stock-week: brackets 1-15 add up to the total (level 17) up to the published
    adjustment (level 16, whose sign the file drops)."""
    by = {lv.level: lv for lv in levels}
    if 17 not in by:
        return ["missing_total"]
    brackets = sum(by[k].shares for k in range(1, 16) if k in by)
    adjustment = by[16].shares if 16 in by else 0
    if abs(brackets - by[17].shares) != adjustment:
        return ["levels_do_not_add_up"]
    return []
