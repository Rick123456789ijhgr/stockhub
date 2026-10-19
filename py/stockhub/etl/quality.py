"""Data quality checks. Rows that fail go to quarantine tables, never to the main tables."""

from __future__ import annotations

from decimal import Decimal

from stockhub.engine.adjustments import implied_reference_price
from stockhub.etl.providers.base import CorporateAction, DailyBar, DividendDetail

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
