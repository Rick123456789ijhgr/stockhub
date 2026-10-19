"""Deterministic fake providers for tests and local runs (no network)."""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import ClassVar

from stockhub.etl.providers.base import (
    DailyBar,
    Market,
    PermanentProviderError,
    PriceProvider,
    RawResponse,
    TransientProviderError,
)
from stockhub.etl.providers.registry import register_provider

DEFAULT_SYMBOLS = ("2330", "0050")


def _fake_bar(symbol: str, day: date) -> dict[str, object]:
    seed = int(hashlib.sha256(f"{symbol}:{day.isoformat()}".encode()).hexdigest()[:8], 16)
    close = Decimal(100 + seed % 900) + Decimal(seed % 100) / 100
    spread = (close * Decimal("0.02")).quantize(Decimal("0.01"))
    volume = 1000 * (1 + seed % 5000)
    return {
        "symbol": symbol,
        "date": day.isoformat(),
        "open": str(close - spread / 2),
        "high": str(close + spread),
        "low": str(close - spread),
        "close": str(close),
        "volume": volume,
        "turnover": str(close * volume),
    }


@register_provider
class FakePriceProvider(PriceProvider):
    """Weekday bars derived from a hash of (symbol, date): stable across runs."""

    name: ClassVar[str] = "fake"
    markets: ClassVar[frozenset[Market]] = frozenset({"twse", "tpex"})

    def __init__(self, symbols: Sequence[str] = DEFAULT_SYMBOLS) -> None:
        self.symbols = tuple(symbols)

    def fetch_daily_prices(self, trade_date: date, market: Market) -> RawResponse:
        rows = (
            [_fake_bar(s, trade_date) for s in self.symbols] if trade_date.isoweekday() < 6 else []
        )
        params = {"date": trade_date.isoformat(), "market": market}
        return RawResponse("daily_prices", {"data": rows}, params)

    def parse_daily_prices(self, raw: RawResponse) -> list[DailyBar]:
        payload = raw.payload
        if isinstance(payload, bytes | str):
            payload = json.loads(payload)
        return [
            DailyBar(
                symbol=r["symbol"],
                trade_date=date.fromisoformat(r["date"]),
                open=Decimal(r["open"]),
                high=Decimal(r["high"]),
                low=Decimal(r["low"]),
                close=Decimal(r["close"]),
                volume=int(r["volume"]),
                turnover=Decimal(r["turnover"]),
            )
            for r in payload["data"]
        ]


@register_provider
class FlakyFakeProvider(FakePriceProvider):
    """FakePriceProvider that fails on purpose.

    - fail_first: the first N fetches fail (deterministic)
    - fail_rate: afterwards, each fetch fails with this probability (seeded)
    - permanent: raise PermanentProviderError instead of a transient error
    """

    name: ClassVar[str] = "flaky_fake"

    def __init__(
        self,
        fail_rate: float = 0.0,
        fail_first: int = 0,
        permanent: bool = False,
        seed: int = 0,
        symbols: Sequence[str] = DEFAULT_SYMBOLS,
    ) -> None:
        super().__init__(symbols)
        if not 0.0 <= fail_rate <= 1.0:
            raise ValueError("fail_rate must be between 0 and 1")
        self.fail_rate, self.fail_first, self.permanent = fail_rate, fail_first, permanent
        self.calls = 0
        self._rng = random.Random(seed)  # noqa: S311 - test fixture

    def fetch_daily_prices(self, trade_date: date, market: Market) -> RawResponse:
        self.calls += 1
        if self.calls <= self.fail_first or self._rng.random() < self.fail_rate:
            error = PermanentProviderError if self.permanent else TransientProviderError
            raise error(f"{self.name}: simulated failure on call {self.calls}")
        return super().fetch_daily_prices(trade_date, market)
