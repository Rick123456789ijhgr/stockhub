"""Deterministic fake providers for tests and local runs (no network)."""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar

from stockhub.etl.providers.base import (
    DailyBar,
    Market,
    PermanentProviderError,
    PriceProvider,
    QuoteStreamProvider,
    QuoteUpdate,
    RawResponse,
    StreamMessage,
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


@register_provider
class FakeQuoteStreamProvider(QuoteStreamProvider):
    """Scripted push feed: tests call `push` and `drop`; no threads, no network.

    - fail_connects: the first N connects fail (transient, or permanent with `permanent`)
    """

    name: ClassVar[str] = "fake_stream"

    def __init__(
        self,
        fail_connects: int = 0,
        permanent: bool = False,
        max_subscriptions: int = 100,
        name: str | None = None,
    ) -> None:
        self.fail_connects, self.permanent = fail_connects, permanent
        self.max_subscriptions = max_subscriptions  # type: ignore[misc]
        if name is not None:
            self.name = name  # type: ignore[misc]
        self.connects = 0
        self.subscribed: dict[str, Market] = {}
        self._connected = False
        self._on_message: Callable[[StreamMessage], None] | None = None
        self._on_lost: Callable[[str], None] | None = None

    def connect(
        self,
        on_message: Callable[[StreamMessage], None],
        on_lost: Callable[[str], None],
    ) -> None:
        self.connects += 1
        if self.connects <= self.fail_connects:
            error = PermanentProviderError if self.permanent else TransientProviderError
            raise error(f"{self.name}: simulated connect failure {self.connects}")
        self._on_message, self._on_lost = on_message, on_lost
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False
        self.subscribed.clear()

    def is_connected(self) -> bool:
        return self._connected

    def subscribe(self, symbols: Sequence[tuple[str, Market]]) -> None:
        if not self._connected:
            raise TransientProviderError("not connected")
        self.subscribed.update(symbols)

    def unsubscribe(self, symbols: Sequence[tuple[str, Market]]) -> None:
        for symbol, _ in symbols:
            self.subscribed.pop(symbol, None)

    def push(self, symbol: str, at: datetime, kind: str = "tick", **fields: Any) -> None:
        """Deliver one message, as the SDK callback would (only while subscribed)."""
        if not self._connected or symbol not in self.subscribed or self._on_message is None:
            return
        payload = {
            "symbol": symbol,
            "market": self.subscribed[symbol],
            "kind": kind,
            "at": at.isoformat(),
            **{k: str(v) for k, v in fields.items()},
        }
        self._on_message(StreamMessage(kind, payload, at))

    def drop(self, reason: str = "simulated drop") -> None:
        self._connected = False
        self.subscribed.clear()
        if self._on_lost is not None:
            self._on_lost(reason)

    def parse_message(self, message: StreamMessage) -> list[QuoteUpdate]:
        p = message.payload
        fields: dict[str, Any] = {
            k: Decimal(p[k])
            for k in ("price", "open", "high", "low", "prev_close", "bid", "ask")
            if k in p
        }
        if "volume" in p:
            fields["volume"] = int(p["volume"])
        return [
            QuoteUpdate(
                symbol=p["symbol"],
                market=p["market"],
                kind=p["kind"],
                at=datetime.fromisoformat(p["at"]),
                **fields,
            )
        ]
