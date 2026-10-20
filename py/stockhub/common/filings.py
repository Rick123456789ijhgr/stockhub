"""Statutory filing deadlines (證券交易法 §36, general companies, IFRS era from 2013).

They are the conservative "data is public by" date when the real publish date is unknown:
valuation and backtests align on publish_date when we saw it, else on these.
Financial companies (M3b) have other half-year deadlines.
"""

from __future__ import annotations

from datetime import date, timedelta

FIRST_SEEN_GRACE = timedelta(days=7)
"""A filing first seen later than its deadline plus this was most likely filed earlier, while
we were not watching (e.g. the first sync); its publish date is then left unknown."""


def quarter_deadline(period_end: date) -> date:
    """Q1 -> 05-15, Q2 -> 08-14, Q3 -> 11-14, annual (Q4) -> 03-31 of the next year."""
    year = period_end.year
    match period_end.month:
        case 3:
            return date(year, 5, 15)
        case 6:
            return date(year, 8, 14)
        case 9:
            return date(year, 11, 14)
        case 12:
            return date(year + 1, 3, 31)
    raise ValueError(f"{period_end} is not a quarter end")


def revenue_deadline(revenue_month: date) -> date:
    """Monthly revenue is due by the 10th of the following month."""
    if revenue_month.month == 12:
        return date(revenue_month.year + 1, 1, 10)
    return date(revenue_month.year, revenue_month.month + 1, 10)


def first_seen_publish_date(today: date, deadline: date) -> date | None:
    """Publish date to record for a filing first seen `today` in an official snapshot."""
    return today if today <= deadline + FIRST_SEEN_GRACE else None


def available_date(period_end: date, publish_date: date | None) -> date:
    """First date a quarter's figures may be used: when we saw them published (late filers
    included), else the deadline."""
    return publish_date if publish_date is not None else quarter_deadline(period_end)
