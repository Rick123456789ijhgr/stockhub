from datetime import date
from decimal import Decimal

import pytest

from stockhub.engine.adjustments import (
    FactorSegment,
    adj_factor_on,
    factor_segments,
    guess_share_ratio,
    implied_reference_price,
)

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


@pytest.mark.parametrize(
    ("price_ratio", "ratio", "action_type"),
    [
        (D("0.25"), D(4), "split"),  # 1 -> 4 split, flat day
        (D("0.1080"), D(10), "split"),  # par 10 -> 1 on a +8% day
        (D("0.2150"), D(5), "split"),  # 0.215 is closer to 1/5 (+7.5%) than 1/4 (-14%)
        (D("0.47"), D(2), "split"),
        (D("9.6"), D("0.1"), "reverse_split"),  # ten shares become one, -4% day
        (D("2.05"), D("0.5"), "reverse_split"),
    ],
)
def test_guess_share_ratio_matches_common_ratios(
    price_ratio: Decimal, ratio: Decimal, action_type: str
) -> None:
    guess = guess_share_ratio(price_ratio)
    assert guess is not None
    assert (guess.ratio, guess.action_type) == (ratio, action_type)
    assert guess.implied_move == (price_ratio * ratio - 1).quantize(D("1E-4"))


@pytest.mark.parametrize("price_ratio", [D("0.35"), D("0.58"), D("1.7"), D("3.2")])
def test_guess_share_ratio_gives_up_on_uncommon_ratios(price_ratio: Decimal) -> None:
    assert guess_share_ratio(price_ratio) is None


def test_guess_share_ratio_rejects_non_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        guess_share_ratio(D(0))


def test_implied_reference_price() -> None:
    # 1773 2025-06-13: cash 2.5 and 200 free shares per 1000 on a 151 close.
    assert implied_reference_price(D(151), D("2.5"), D("0.2")) == D("123.75")
    # 6225 2026-08-18: whole offering 1.1583 per share subscribed at 17.65 on a 44.40 close.
    implied = implied_reference_price(D("44.40"), D(0), D(0), D("1.15827338"), D("17.65"))
    assert abs(implied - D("30.04")) < D("0.01")
