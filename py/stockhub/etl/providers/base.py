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

DataKind = Literal["price", "financial", "quote"]


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
    @abstractmethod
    def fetch_daily_prices(
        self, start: date, end: date, symbols: Sequence[str] | None = None
    ) -> RawResponse:
        """Daily bars for [start, end]; symbols=None means the whole market."""

    @abstractmethod
    def parse_daily_prices(self, raw: RawResponse) -> list[DailyBar]: ...


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
}
