from datetime import date
from decimal import Decimal

import pytest

from stockhub.engine.adjustments import FactorSegment, adj_factor_on, factor_segments

D = Decimal


def test_no_events_means_no_adjustment() -> None:
    assert factor_segments([]) == [FactorSegment(None, None, D(1))]


def test_single_cash_dividend() -> None:
    # 2330-like: close 1000 before ex-date, reference 990 after a 10 dividend.
    segments = factor_segments([(date(2025, 6, 12), D(990) / D(1000))])
    assert segments == [
        FactorSegment(None, date(2025, 6, 12), D("0.9900000000")),
        FactorSegment(date(2025, 6, 12), None, D(1)),
    ]
    assert adj_factor_on(segments, date(2025, 6, 11)) == D("0.99")
    assert adj_factor_on(segments, date(2025, 6, 12)) == 1


def test_factors_compound_backwards_and_same_day_events_multiply() -> None:
    split = D("47.16") / D("188.65")  # 0050 split 1 -> 4 on 2025-06-18
    dividend = D("0.98")
    reduction = D("1.5")
    segments = factor_segments(
        [
            (date(2025, 6, 18), split),
            (date(2024, 7, 16), dividend),
            (date(2024, 7, 16), reduction),  # same day: multiplied
        ]
    )
    assert [(s.start, s.end) for s in segments] == [
        (None, date(2024, 7, 16)),
        (date(2024, 7, 16), date(2025, 6, 18)),
        (date(2025, 6, 18), None),
    ]
    rounded_split = split.quantize(D("1E-10"))
    assert segments[1].factor == rounded_split
    assert segments[0].factor == (split * dividend * reduction).quantize(D("1E-10"))
    assert segments[-1].factor == 1


def test_adjusted_series_has_no_jump_on_the_ex_date() -> None:
    # Raw closes: 100 before, then the stock trades at its reference price 95 after a 5 dividend.
    segments = factor_segments([(date(2025, 7, 1), D(95) / D(100))])
    before = D(100) * adj_factor_on(segments, date(2025, 6, 30))
    after = D(95) * adj_factor_on(segments, date(2025, 7, 1))
    assert before == after


def test_rejects_non_positive_factors() -> None:
    with pytest.raises(ValueError, match="positive"):
        factor_segments([(date(2025, 1, 2), D(0))])
