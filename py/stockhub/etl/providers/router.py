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
from typing import Literal

from stockhub.common.rawstore import RawObject, RawStore
from stockhub.common.settings import ConfigError
from stockhub.etl.providers.base import (
    ActionDataset,
    AllProvidersFailedError,
    Attempt,
    CalendarEntry,
    CalendarProvider,
    CompanyProfile,
    CompanyProfileProvider,
    CorporateAction,
    CorporateActionProvider,
    DailyBar,
    DataKind,
    Delisting,
    DelistingProvider,
    DistributionLevel,
    DividendDetail,
    DividendDetailProvider,
    ExRightsPreview,
    ExRightsPreviewProvider,
    FinancialItem,
    FinancialProvider,
    FinancialSnapshotProvider,
    ForeignHolding,
    ForeignHoldingProvider,
    InstitutionalTrade,
    InstitutionalTradeProvider,
    MacroReleaseProvider,
    MarginProvider,
    MarginTable,
    Market,
    MarketInstitutional,
    MarketInstitutionalProvider,
    MarketSeriesProvider,
    MonthlyRevenue,
    MonthlyRevenueProvider,
    MonthlyRevenueSnapshotProvider,
    PermanentProviderError,
    PriceProvider,
    Provider,
    ProviderParseError,
    Quote,
    QuoteProvider,
    RawResponse,
    Security,
    SecurityListProvider,
    SeriesObservation,
    ShareholdingDistributionProvider,
    Statement,
)
from stockhub.etl.providers.registry import ProviderRegistry

log = logging.getLogger(__name__)

ChipKind = Literal["institutional_trades", "margin", "foreign_holdings", "market_institutional"]
CHIP_SINCE: dict[ChipKind, str] = {
    "institutional_trades": "institutional_since",
    "margin": "margin_since",
    "foreign_holdings": "foreign_holding_since",
    "market_institutional": "market_institutional_since",
}
"""Chip data kind -> the provider attribute mapping each market to its first date."""


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

    def delistings(self, market: Market, year: int) -> Fetched[Delisting]:
        return self._call(
            "delistings",
            DelistingProvider,
            lambda p: p.fetch_delistings(market, year),
            lambda p, raw: p.parse_delistings(raw),
            accepts=lambda p: market in p.delisting_markets,
        )

    def corporate_action_since(self, market: Market, dataset: ActionDataset) -> date | None:
        """Earliest date any configured source covers for this table; None if none does."""
        try:
            providers = self.registry.providers_for("corporate_actions")
        except ConfigError:
            return None
        dates = [
            p.action_sources[(market, dataset)]
            for p in providers
            if isinstance(p, CorporateActionProvider) and (market, dataset) in p.action_sources
        ]
        return min(dates, default=None)

    def corporate_actions(
        self, market: Market, dataset: ActionDataset, start: date, end: date
    ) -> Fetched[CorporateAction]:
        def accepts(p: CorporateActionProvider) -> bool:
            since = p.action_sources.get((market, dataset))
            return since is not None and end >= since

        return self._call(
            "corporate_actions",
            CorporateActionProvider,
            lambda p: p.fetch_corporate_actions(
                market, dataset, max(start, p.action_sources[(market, dataset)]), end
            ),
            lambda p, raw: p.parse_corporate_actions(raw),
            accepts=accepts,
        )

    def dividend_detail_since(self, market: Market) -> date | None:
        """Earliest ex-date any configured detail source covers; None if none does."""
        try:
            providers = self.registry.providers_for("dividend_details")
        except ConfigError:
            return None
        dates = [
            p.detail_since
            for p in providers
            if isinstance(p, DividendDetailProvider) and market in p.detail_markets
        ]
        return min(dates, default=None)

    def dividend_detail(
        self, market: Market, symbol: str, ex_date: date
    ) -> Fetched[DividendDetail]:
        return self._call(
            "dividend_details",
            DividendDetailProvider,
            lambda p: p.fetch_dividend_detail(market, symbol, ex_date),
            lambda p, raw: p.parse_dividend_detail(raw),
            accepts=lambda p: market in p.detail_markets and ex_date >= p.detail_since,
        )

    def ex_rights_previews(self, market: Market) -> Fetched[ExRightsPreview]:
        return self._call(
            "ex_rights_previews",
            ExRightsPreviewProvider,
            lambda p: p.fetch_ex_rights_previews(market),
            lambda p, raw: p.parse_ex_rights_previews(raw),
            accepts=lambda p: market in p.preview_markets,
        )

    def financials(self, symbol: str, statement: Statement, start: date) -> Fetched[FinancialItem]:
        return self._call(
            "financial",
            FinancialProvider,
            lambda p: p.fetch_financials(symbol, statement, start),
            lambda p, raw: p.parse_financials(raw),
        )

    def financial_snapshot(self, market: Market, statement: Statement) -> Fetched[FinancialItem]:
        return self._call(
            "financial_snapshot",
            FinancialSnapshotProvider,
            lambda p: p.fetch_financial_snapshot(market, statement),
            lambda p, raw: p.parse_financial_snapshot(raw),
            accepts=lambda p: market in p.snapshot_markets,
        )

    def monthly_revenue(self, symbol: str, start: date) -> Fetched[MonthlyRevenue]:
        return self._call(
            "monthly_revenue",
            MonthlyRevenueProvider,
            lambda p: p.fetch_monthly_revenue(symbol, start),
            lambda p, raw: p.parse_monthly_revenue(raw),
        )

    def monthly_revenue_snapshot(self, market: Market) -> Fetched[MonthlyRevenue]:
        return self._call(
            "monthly_revenue_snapshot",
            MonthlyRevenueSnapshotProvider,
            lambda p: p.fetch_monthly_revenue_snapshot(market),
            lambda p, raw: p.parse_monthly_revenue_snapshot(raw),
            accepts=lambda p: market in p.revenue_markets,
        )

    def company_profiles(self, market: Market) -> Fetched[CompanyProfile]:
        return self._call(
            "company_profiles",
            CompanyProfileProvider,
            lambda p: p.fetch_company_profiles(market),
            lambda p, raw: p.parse_company_profiles(raw),
            accepts=lambda p: market in p.profile_markets,
        )

    # ------------------------------------------------------------------ chips

    def chip_since(self, kind: ChipKind, market: Market) -> date | None:
        """First date any configured source publishes this chip table for the market; None
        when no source covers the market."""
        try:
            providers = self.registry.providers_for(kind)
        except ConfigError:
            return None
        since: dict[Market, date]
        dates = [
            since[market]
            for p in providers
            if market in (since := getattr(p, CHIP_SINCE[kind], {}))
        ]
        return min(dates, default=None)

    def _chip_accepts(
        self, kind: ChipKind, market: Market, day: date
    ) -> Callable[[Provider], bool]:
        def accepts(p: Provider) -> bool:
            since: dict[Market, date] = getattr(p, CHIP_SINCE[kind], {})
            return market in since and day >= since[market]

        return accepts

    def institutional_trades(self, day: date, market: Market) -> Fetched[InstitutionalTrade]:
        return self._call(
            "institutional_trades",
            InstitutionalTradeProvider,
            lambda p: p.fetch_institutional_trades(day, market),
            lambda p, raw: p.parse_institutional_trades(raw),
            accepts=self._chip_accepts("institutional_trades", market, day),
        )

    def margin(self, day: date, market: Market) -> Fetched[MarginTable]:
        return self._call(
            "margin",
            MarginProvider,
            lambda p: p.fetch_margin(day, market),
            lambda p, raw: p.parse_margin(raw),
            accepts=self._chip_accepts("margin", market, day),
        )

    def foreign_holdings(self, day: date, market: Market) -> Fetched[ForeignHolding]:
        return self._call(
            "foreign_holdings",
            ForeignHoldingProvider,
            lambda p: p.fetch_foreign_holdings(day, market),
            lambda p, raw: p.parse_foreign_holdings(raw),
            accepts=self._chip_accepts("foreign_holdings", market, day),
        )

    def market_institutional(self, day: date, market: Market) -> Fetched[MarketInstitutional]:
        return self._call(
            "market_institutional",
            MarketInstitutionalProvider,
            lambda p: p.fetch_market_institutional(day, market),
            lambda p, raw: p.parse_market_institutional(raw),
            accepts=self._chip_accepts("market_institutional", market, day),
        )

    def shareholding_distribution(self) -> Fetched[DistributionLevel]:
        return self._call(
            "shareholding_distribution",
            ShareholdingDistributionProvider,
            lambda p: p.fetch_shareholding_distribution(),
            lambda p, raw: p.parse_shareholding_distribution(raw),
        )

    # ------------------------------------------------------------------ markets and macro

    def series_providers(self, code: str) -> list[MarketSeriesProvider]:
        """Configured sources of a series in fallback order (empty when none serves it)."""
        try:
            providers = self.registry.providers_for("market_series")
        except ConfigError:
            return []
        return [
            p for p in providers if isinstance(p, MarketSeriesProvider) and code in p.series_symbols
        ]

    def series_monthly(self, code: str) -> bool:
        """Whether a source of the series answers one month per request, so a range should be
        requested month by month to give it the chance."""
        return any(p.series_monthly for p in self.series_providers(code))

    def market_series(self, code: str, start: date, end: date) -> Fetched[SeriesObservation]:
        same_month = (start.year, start.month) == (end.year, end.month)
        return self._call(
            "market_series",
            MarketSeriesProvider,
            lambda p: p.fetch_market_series(code, start, end),
            lambda p, raw: p.parse_market_series(raw),
            accepts=lambda p: code in p.series_symbols and (same_month or not p.series_monthly),
        )

    def macro_release(self) -> Fetched[SeriesObservation]:
        return self._call(
            "macro_release",
            MacroReleaseProvider,
            lambda p: p.fetch_macro_release(),
            lambda p, raw: p.parse_macro_release(raw),
        )

    def quotes(self, symbols: Sequence[tuple[str, Market]]) -> Fetched[Quote]:
        """One batch (at most QuoteProvider.max_symbols; callers split longer lists)."""
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
