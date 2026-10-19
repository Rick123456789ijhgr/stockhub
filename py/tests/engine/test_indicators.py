"""Indicators: hand-checked small cases, plus the shared fixture the web tests also use."""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from stockhub.common.settings import PROJECT_ROOT
from stockhub.engine import indicators as ind

FIXTURE = PROJECT_ROOT / "testdata" / "indicators.json"


def test_sma() -> None:
    assert ind.sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]
    assert ind.sma([1, 2], 3) == [None, None]


def test_ema_is_seeded_with_the_sma() -> None:
    out = ind.ema([1, 2, 3, 4], 3)
    # seed = mean(1, 2, 3) = 2; then 0.5 * 4 + 0.5 * 2 = 3
    assert out == [None, None, 2.0, 3.0]


def test_kd_starts_from_50_and_handles_flat_ranges() -> None:
    out = ind.kd([10, 10], [10, 10], [10, 10], n=1)
    assert out.k == [50.0, 50.0]
    rising = ind.kd([11, 12], [9, 10], [11, 12], n=2)
    # RSV on day 2 = (12 - 9) / (12 - 9) * 100 = 100; K = (2*50 + 100) / 3
    assert rising.k[0] is None
    assert rising.k[1] == pytest.approx(200 / 3)
    assert rising.d[1] == pytest.approx((100 + 200 / 3) / 3)


def test_rsi_extremes_and_wilder_smoothing() -> None:
    assert ind.rsi([1, 2, 3, 4], n=3)[3] == 100.0
    assert ind.rsi([5, 5, 5, 5], n=3)[3] == 50.0
    out = ind.rsi([10, 11, 10, 11, 12], n=2)
    # first: gains (1, 0) -> 0.5, losses (0, 1) -> 0.5 -> RSI 50
    assert out[2] == 50.0
    # next: gain (0.5*1 + 1) / 2 = 0.75, loss 0.5/2 = 0.25 -> 100 - 100/4 = 75
    assert out[3] == pytest.approx(75.0)


def test_macd_lines_start_after_the_slow_ema_and_signal() -> None:
    closes = [float(i) for i in range(1, 41)]
    out = ind.macd(closes)
    assert out.dif[24] is None
    assert out.dif[25] is not None
    assert out.signal[32] is None
    assert out.signal[33] is not None
    assert out.histogram[33] == pytest.approx(out.dif[33] - out.signal[33])  # type: ignore[operator]


def _close(actual: list[float | None], expected: list[Any]) -> bool:
    if len(actual) != len(expected):
        return False
    for a, e in zip(actual, expected, strict=True):
        if (a is None) != (e is None):
            return False
        if a is not None and not math.isclose(a, e, rel_tol=1e-12, abs_tol=1e-12):
            return False
    return True


def test_shared_fixture_matches() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    high, low, close = (data["input"][k] for k in ("high", "low", "close"))
    macd = ind.macd(close)
    kd = ind.kd(high, low, close)
    actual = {
        "sma5": ind.sma(close, 5),
        "sma20": ind.sma(close, 20),
        "sma60": ind.sma(close, 60),
        "ema12": ind.ema(close, 12),
        "macd_dif": macd.dif,
        "macd_signal": macd.signal,
        "macd_histogram": macd.histogram,
        "kd_k": kd.k,
        "kd_d": kd.d,
        "rsi14": ind.rsi(close),
    }
    assert actual.keys() == data["expected"].keys()
    for name, values in actual.items():
        assert _close(values, data["expected"][name]), name
