"""Valuation formulas (engine/valuation.py) and the shared fixture testdata/valuation.json."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from stockhub.engine import valuation as v

FIXTURE = Path(__file__).resolve().parents[3] / "testdata" / "valuation.json"


def _load() -> dict:  # type: ignore[type-arg]
    return json.loads(FIXTURE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_fixture_is_current() -> None:
    data = _load()
    prices = [v.PricePoint(**p) for p in data["input"]["prices"]]
    quarters = [v.QuarterPoint(**q) for q in data["input"]["quarters"]]
    dividends = [v.Dividend(**d) for d in data["input"]["dividends"]]
    series = v.valuation_series(prices, quarters, dividends)
    assert [asdict(p) for p in series] == data["expected"]["series"], (
        "regenerate with: uv run python scripts/gen_valuation_fixture.py"
    )


def test_quarter_is_used_from_its_available_date() -> None:
    quarters = [
        v.QuarterPoint("2025-12-31", "2026-03-31", 4.0, 40.0),
        v.QuarterPoint("2026-03-31", "2026-05-15", -1.0, 41.0),
    ]
    prices = [v.PricePoint(d, 100.0) for d in ("2026-03-30", "2026-03-31", "2026-05-15")]
    series = v.valuation_series(prices, quarters, [])
    assert [p.pe for p in series] == [None, 25.0, None]  # before availability; then a loss
    assert [p.pb for p in series] == [None, 2.5, 100.0 / 41.0]


def test_trailing_yield_window_excludes_exactly_one_year_ago() -> None:
    dividends = [v.Dividend("2025-03-31", 3.0), v.Dividend("2025-04-01", 2.0)]
    point = v.valuation_series([v.PricePoint("2026-03-31", 50.0)], [], dividends)[0]
    assert point.dividend_ttm == 2.0
    assert point.dividend_yield == pytest.approx(0.04)


def test_percentile_bands_and_quantiles() -> None:
    assert v.percentile_rank([10, 20, 30, 40], 30) == 0.625
    assert v.quantile([1, 2, 3, 4, 5], 0.25) == 2
    assert v.band_multiples([10.0] * 5) == [10.0]
    multiples = v.band_multiples([float(x) for x in range(101)])
    assert multiples == pytest.approx([5, 27.5, 50, 72.5, 95])
    assert v.shift_years("2024-02-29", -1) == "2023-02-28"
