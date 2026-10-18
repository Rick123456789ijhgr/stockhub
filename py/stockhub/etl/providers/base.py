"""Provider interfaces: every data source (official or not) is an adapter behind these.

Each capability is split into fetch_* (network I/O, returns the raw response) and parse_*
(pure, raw -> pydantic models). The router lands the raw response in RawStore between the
two steps, so a parser bug never loses data (CLAUDE.md rules 5 and 6).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

DataKind = Literal["price", "financial", "quote", "calendar", "securities"]
Market = Literal["twse", "tpex"]
"""twse = listed (上市), tpex = OTC (上櫃); matches stocks.market."""


# ----------------------------------------------------------------------------- errors


class ProviderError(Exception):
    """Base class for provider failures."""


class TransientProviderError(ProviderError):
    """Worth retrying: timeouts, 5xx, throttling."""


class PermanentProviderError(ProviderError):
    """Retrying the same source will not help: bad request, unsupported query, auth."""


class ProviderParseError(PermanentProviderError):
    """The response was fetched (and stored) but could not be parsed."""


@dataclass(frozen=True)
class Attempt:
    provider: str
    attempt: int
    error: str


class AllProvidersFailedError(ProviderError):
    """Every configured provider for a data kind failed."""

    def __init__(self, kind: DataKind, attempts: Sequence[Attempt]) -> None:
        self.kind = kind
        self.attempts = list(attempts)
        tried = "; ".join(f"{a.provider}#{a.attempt}: {a.error}" for a in attempts) or "none"
        super().__init__(f"all {kind} providers failed ({tried})")


# ----------------------------------------------------------------------------- models


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DailyBar(_Model):
    """One unadjusted daily bar. OHLC are None when the security did not trade."""

    symbol: str
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: int = Field(ge=0, description="shares")
    turnover: Decimal = Field(ge=0, description="TWD")


class CalendarEntry(_Model):
    """A date the exchange announced as special: a holiday, or an explicit trading day."""

    day: date
    name: str
    is_trading_day: bool


class Security(_Model):
    """One listed security from an exchange's master list."""

    symbol: str
    name: str
    market: Market
    type: Literal["stock", "etf"]
    listed_date: date
    industry: str | None = None
    isin: str | None = None


class FinancialItem(_Model):
    """One reported line item, as published (usually year-to-date)."""

    symbol: str
    period_end: date
    period_type: Literal["Q", "Y"]
    statement: Literal["IS", "BS", "CF"]
    item_code: str
    value: Decimal
    publish_date: date | None = None


class Quote(_Model):
    """Intraday snapshot."""

    symbol: str
    price: Decimal
    volume: int = Field(ge=0, description="cumulative shares today")
    at: AwareDatetime


@dataclass(frozen=True)
class RawResponse:
    """What a fetch returned, before parsing; landed in RawStore by the router."""

    dataset: str
    payload: bytes | str | Any
    params: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------------- interfaces


class Provider(ABC):
    name: ClassVar[str]
    """Registry key, also used as the RawStore provider segment."""
    min_interval: ClassVar[float] = 0.0
    """Minimum seconds between calls to this source (rate limit)."""


class PriceProvider(Provider):
    markets: ClassVar[frozenset[Market]]
    """Markets this source can serve; the router skips it for others."""

    @abstractmethod
    def fetch_daily_prices(self, trade_date: date, market: Market) -> RawResponse:
        """All bars of one market on one date (official sources publish whole-market days)."""

    @abstractmethod
    def parse_daily_prices(self, raw: RawResponse) -> list[DailyBar]:
        """Empty list = the market did not trade that day."""


class CalendarProvider(Provider):
    @abstractmethod
    def fetch_calendar(self, year: int) -> RawResponse: ...

    @abstractmethod
    def parse_calendar(self, raw: RawResponse) -> list[CalendarEntry]:
        """Announced special dates of the year; an empty list means not published."""


class SecurityListProvider(Provider):
    security_markets: ClassVar[frozenset[Market]]
    """Markets whose master list this source publishes (separate from price markets)."""

    @abstractmethod
    def fetch_securities(self, market: Market) -> RawResponse: ...

    @abstractmethod
    def parse_securities(self, raw: RawResponse) -> list[Security]: ...


class FinancialProvider(Provider):
    @abstractmethod
    def fetch_financials(self, symbol: str, period_end: date) -> RawResponse: ...

    @abstractmethod
    def parse_financials(self, raw: RawResponse) -> list[FinancialItem]: ...


class QuoteProvider(Provider):
    @abstractmethod
    def fetch_quotes(self, symbols: Sequence[str]) -> RawResponse: ...

    @abstractmethod
    def parse_quotes(self, raw: RawResponse) -> list[Quote]: ...


INTERFACES: dict[DataKind, type[Provider]] = {
    "price": PriceProvider,
    "financial": FinancialProvider,
    "quote": QuoteProvider,
    "calendar": CalendarProvider,
    "securities": SecurityListProvider,
}
