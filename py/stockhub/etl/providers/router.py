"""Resilient provider calls: rate limit, retry with exponential backoff, fallback, RawStore.

Flow per provider (in registry order):
  rate-limit -> fetch (retry transient errors with backoff) -> land raw in RawStore -> parse
A permanent error, a parse error or exhausted retries moves on to the next provider; when
none succeeds AllProvidersFailedError lists every attempt.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

from stockhub.common.rawstore import RawObject, RawStore
from stockhub.common.settings import ConfigError
from stockhub.etl.providers.base import (
    AllProvidersFailedError,
    Attempt,
    CalendarEntry,
    CalendarProvider,
    DailyBar,
    DataKind,
    FinancialItem,
    FinancialProvider,
    Market,
    PermanentProviderError,
    PriceProvider,
    Provider,
    ProviderParseError,
    Quote,
    QuoteProvider,
    RawResponse,
    Security,
    SecurityListProvider,
)
from stockhub.etl.providers.registry import ProviderRegistry

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter: float = 0.1
    """Fraction of the delay added as random jitter (0 disables)."""

    def delay(self, attempt: int, rng: random.Random) -> float:
        """Backoff before retry number `attempt` (1-based count of failures so far)."""
        delay = min(self.max_delay, self.base_delay * 2 ** (attempt - 1))
        return float(delay + delay * self.jitter * rng.random())


class RateLimiter:
    """Minimum interval between calls, per provider name."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._clock, self._sleep = clock, sleep
        self._last: dict[str, float] = {}

    def wait(self, name: str, min_interval: float) -> None:
        last = self._last.get(name)
        if last is not None and min_interval > 0:
            remaining = last + min_interval - self._clock()
            if remaining > 0:
                self._sleep(remaining)
        self._last[name] = self._clock()


@dataclass(frozen=True)
class Fetched[T]:
    items: list[T]
    provider: str
    raw: RawObject
    attempts: list[Attempt] = field(default_factory=list)
    """Failed attempts before the successful one (empty on a clean primary hit)."""

    @property
    def used_fallback(self) -> bool:
        return any(a.provider != self.provider for a in self.attempts)


class ProviderRouter:
    def __init__(
        self,
        registry: ProviderRegistry,
        rawstore: RawStore,
        retry: RetryPolicy | None = None,
        limiter: RateLimiter | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.registry = registry
        self.rawstore = rawstore
        self.retry = retry or RetryPolicy()
        self.limiter = limiter or RateLimiter(sleep=sleep)
        self._sleep = sleep
        self._rng = rng or random.Random()  # noqa: S311 - jitter, not crypto

    # ------------------------------------------------------------------ public API

    def daily_prices(self, trade_date: date, market: Market) -> Fetched[DailyBar]:
        return self._call(
            "price",
            PriceProvider,
            lambda p: p.fetch_daily_prices(trade_date, market),
            lambda p, raw: p.parse_daily_prices(raw),
            accepts=lambda p: market in p.markets,
        )

    def calendar(self, year: int) -> Fetched[CalendarEntry]:
        return self._call(
            "calendar",
            CalendarProvider,
            lambda p: p.fetch_calendar(year),
            lambda p, raw: p.parse_calendar(raw),
        )

    def securities(self, market: Market) -> Fetched[Security]:
        return self._call(
            "securities",
            SecurityListProvider,
            lambda p: p.fetch_securities(market),
            lambda p, raw: p.parse_securities(raw),
            accepts=lambda p: market in p.security_markets,
        )

    def financials(self, symbol: str, period_end: date) -> Fetched[FinancialItem]:
        return self._call(
            "financial",
            FinancialProvider,
            lambda p: p.fetch_financials(symbol, period_end),
            lambda p, raw: p.parse_financials(raw),
        )

    def quotes(self, symbols: Sequence[str]) -> Fetched[Quote]:
        return self._call(
            "quote",
            QuoteProvider,
            lambda p: p.fetch_quotes(symbols),
            lambda p, raw: p.parse_quotes(raw),
        )

    # ------------------------------------------------------------------ internals

    def _call[P: Provider, T](
        self,
        kind: DataKind,
        interface: type[P],
        fetch: Callable[[P], RawResponse],
        parse: Callable[[P, RawResponse], list[T]],
        accepts: Callable[[P], bool] | None = None,
    ) -> Fetched[T]:
        failures: list[Attempt] = []
        candidates: list[P] = []
        for provider in self.registry.providers_for(kind):
            if not isinstance(provider, interface):  # guaranteed by the registry
                raise TypeError(f"{provider.name} is not a {interface.__name__}")
            if accepts is None or accepts(provider):
                candidates.append(provider)
        if not candidates:
            raise ConfigError(f"no configured {kind} provider supports this request")
        for index, provider in enumerate(candidates):
            if index > 0:
                log.warning(
                    "%s provider %s failed; falling back to %s",
                    kind,
                    failures[-1].provider,
                    provider.name,
                )
            result = self._try_provider(provider, fetch, parse, failures)
            if result is not None:
                items, raw = result
                return Fetched(items, provider.name, raw, failures)
        raise AllProvidersFailedError(kind, failures)

    def _try_provider[P: Provider, T](
        self,
        provider: P,
        fetch: Callable[[P], RawResponse],
        parse: Callable[[P, RawResponse], list[T]],
        failures: list[Attempt],
    ) -> tuple[list[T], RawObject] | None:
        for attempt in range(1, self.retry.max_attempts + 1):
            self.limiter.wait(provider.name, provider.min_interval)
            try:
                response = fetch(provider)
            except PermanentProviderError as exc:
                failures.append(Attempt(provider.name, attempt, f"permanent: {exc}"))
                return None
            except Exception as exc:  # transient or unknown: retry
                failures.append(Attempt(provider.name, attempt, f"{type(exc).__name__}: {exc}"))
                if attempt < self.retry.max_attempts:
                    self._sleep(self.retry.delay(attempt, self._rng))
                continue

            raw = self.rawstore.put(
                provider.name, response.dataset, response.payload, params=response.params
            )
            try:
                return parse(provider, response), raw
            except Exception as exc:
                error = ProviderParseError(f"{type(exc).__name__}: {exc} (raw: {raw.uri})")
                failures.append(Attempt(provider.name, attempt, f"parse: {error}"))
                log.error("%s could not parse %s: %s", provider.name, raw.uri, exc)
                return None
        return None
