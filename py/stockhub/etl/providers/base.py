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

DataKind = Literal[
    "price",
    "financial",
    "quote",
    "calendar",
    "securities",
    "delistings",
    "corporate_actions",
    "dividend_details",
    "ex_rights_previews",
    "financial_snapshot",
    "monthly_revenue",
    "monthly_revenue_snapshot",
    "company_profiles",
    "institutional_trades",
    "margin",
    "foreign_holdings",
    "market_institutional",
    "shareholding_distribution",
]
Market = Literal["twse", "tpex"]
"""twse = listed (上市), tpex = OTC (上櫃); matches stocks.market."""
ActionDataset = Literal["dividend", "capital_reduction", "par_value_change", "etf_split"]
"""Exchange tables of price-adjusting events: 除權息, 減資, 變更面額, ETF 分割."""
ActionType = Literal[
    "cash_dividend",
    "stock_dividend",
    "cash_and_stock_dividend",
    "rights_issue",
    "capital_reduction",
    "split",
    "reverse_split",
]


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
    name: str | None = None
    """Security name as printed in the day's table (finds securities missing from the master)."""


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


class Delisting(_Model):
    """A security the exchange stopped listing (終止上市／終止上櫃)."""

    symbol: str
    name: str
    market: Market
    delisted_date: date
    """First day it no longer traded; the last trading day is the trading day before."""
    reason: str | None = None


class CorporateAction(_Model):
    """A price-adjusting event as published with its exchange reference price.

    The exchange's reference price already accounts for everything that changed per-share
    value (cash, stock dividends, rights, refunds, ratio changes), so
    reference_price / prev_close is the backward adjustment for that day. ETF splits on
    TPEx carry only a ratio, which then stands in for the prices.
    """

    symbol: str
    market: Market
    ex_date: date
    """First trading day at the new basis (ex-date, or the day trading resumes)."""
    action_type: ActionType
    # Not constrained here: sources publish the odd junk row (0.00 / negative prices), which
    # the quality check quarantines instead of failing the whole table.
    prev_close: Decimal | None = None
    reference_price: Decimal | None = None
    cash_dividend: Decimal | None = Field(default=None, ge=0)
    """Cash per share (dividend, or capital refund for reductions); None when not published."""
    stock_dividend_ratio: Decimal | None = Field(default=None, ge=0)
    ratio: Decimal | None = Field(default=None, gt=0)
    """Shares after / shares before (reductions, splits)."""


class DividendDetail(_Model):
    """What one 除權息 event consisted of, per existing share (TWSE publishes only the total
    in its event table since 2009; the per-event detail page has the parts)."""

    symbol: str
    ex_date: date
    cash_dividend: Decimal = Field(ge=0)
    """Cash per share in TWD."""
    stock_dividend_ratio: Decimal = Field(ge=0)
    """Free new shares per existing share (無償配股; 0.05 = 50 per 1000)."""
    rights_ratio: Decimal = Field(ge=0)
    """New shares existing holders may subscribe per share (現金增資認購; 0 when none)."""
    subscription_price: Decimal | None = Field(default=None, gt=0)
    """Price per subscribed share (每股認購金額); None without a subscription."""


PreviewActionType = Literal[
    "cash_dividend", "stock_dividend", "cash_and_stock_dividend", "rights_issue"
]


class ExRightsPreview(_Model):
    """An announced upcoming 除權息 (除權除息預告表). Amounts may still be unannounced."""

    symbol: str
    market: Market
    ex_date: date
    label: Literal["息", "權", "權息"]
    """The exchange's label."""
    action_type: PreviewActionType
    cash_dividend: Decimal | None = Field(default=None, ge=0)
    """Cash per share; None while the amount is not announced (ETFs often publish it late)."""
    stock_dividend_ratio: Decimal = Field(default=Decimal(0), ge=0)
    """Free new shares per existing share."""
    rights_ratio: Decimal = Field(default=Decimal(0), ge=0)
    """All new shares of a cash offering per existing share (as in DividendDetail)."""
    subscription_price: Decimal | None = Field(default=None, gt=0)


def preview_action_type(
    label: str, cash: Decimal | None, stock_ratio: Decimal, rights_ratio: Decimal
) -> PreviewActionType:
    """Classify a preview by what it carries; the label only decides an all-zero row."""
    if stock_ratio > 0:
        return "cash_and_stock_dividend" if cash else "stock_dividend"
    if cash or "息" in label:
        return "cash_dividend"
    return "rights_issue" if rights_ratio > 0 or label == "權" else "cash_dividend"


Statement = Literal["IS", "BS", "CF"]
Basis = Literal["quarter", "ytd", "instant"]
"""quarter = that quarter alone; ytd = fiscal year-to-date (Q4 = full year); instant = balance."""


class FinancialItem(_Model):
    """One line item as the source reports it, under a canonical item code
    (financial_item_map, industry_type 'general'); amounts in TWD, EPS per share."""

    symbol: str
    period_end: date
    """Quarter end (03-31, 06-30, 09-30, 12-31)."""
    statement: Statement
    item_code: str
    value: Decimal
    basis: Basis
    period_type: Literal["Q", "Y"] = "Q"


class MonthlyRevenue(_Model):
    """One month's revenue (營業收入) of a company, in TWD."""

    symbol: str
    revenue_month: date
    """First day of the revenue month."""
    revenue: Decimal
    publish_date: date | None = None
    """When the source says it was published, if it does."""


class CompanyProfile(_Model):
    """Company basic data (公司基本資料) that the stock master list does not carry."""

    symbol: str
    market: Market
    industry_code: str | None = None
    par_value: Decimal | None = Field(default=None, gt=0)
    """TWD per common share; None when not stated in TWD."""
    issued_shares: int | None = Field(default=None, ge=0)


class InstitutionalTrade(_Model):
    """Shares one stock was bought and sold by the institutional groups on one day (三大法人).

    foreign_* excludes foreign dealers, who the exchanges count among dealers; total_net is
    the exchange's own sum (foreign + trust + dealer). Groups an older table format did not
    split out are None.
    """

    symbol: str
    trade_date: date
    foreign_buy: int = Field(ge=0)
    foreign_sell: int = Field(ge=0)
    foreign_net: int
    foreign_dealer_buy: int | None = Field(default=None, ge=0)
    foreign_dealer_sell: int | None = Field(default=None, ge=0)
    foreign_dealer_net: int | None = None
    trust_buy: int = Field(ge=0)
    trust_sell: int = Field(ge=0)
    trust_net: int
    dealer_buy: int = Field(ge=0)
    dealer_sell: int = Field(ge=0)
    dealer_net: int
    dealer_self_net: int | None = None
    dealer_hedge_net: int | None = None
    total_net: int


class MarginBalance(_Model):
    """One stock's margin purchases (融資) and short sales (融券) on one day, in shares.

    The previous balances are kept for the continuity check; they are not stored.
    """

    symbol: str
    trade_date: date
    margin_buy: int = Field(ge=0)
    margin_sell: int = Field(ge=0)
    margin_redeem: int = Field(ge=0)
    margin_prev: int = Field(ge=0)
    margin_balance: int = Field(ge=0)
    margin_limit: int | None = Field(default=None, ge=0)
    short_sell: int = Field(ge=0)
    short_cover: int = Field(ge=0)
    short_redeem: int = Field(ge=0)
    short_prev: int = Field(ge=0)
    short_balance: int = Field(ge=0)
    short_limit: int | None = Field(default=None, ge=0)
    offset_shares: int = Field(default=0, ge=0)
    note: str | None = None


class MarketMargin(_Model):
    """Whole-market balances from a margin table's summary rows."""

    market: Market
    trade_date: date
    margin_balance: int = Field(ge=0, description="shares")
    short_balance: int = Field(ge=0, description="shares")
    margin_balance_amount: Decimal | None = Field(default=None, ge=0, description="TWD")


class MarginTable(_Model):
    """A whole margin table: per-stock rows plus the market totals it prints."""

    market: Market
    trade_date: date
    rows: list[MarginBalance]
    total: MarketMargin | None = None


class ForeignHolding(_Model):
    """Shares held by all foreign and mainland investors after one day (外資持股)."""

    symbol: str
    trade_date: date
    issued_shares: int = Field(ge=0)
    foreign_shares: int = Field(ge=0)
    foreign_ratio: Decimal
    """Fraction as published (0.7234 = 72.34%); not constrained here, the quality check is."""
    limit_ratio: Decimal | None = None


Investor = Literal[
    "foreign", "foreign_dealer", "trust", "dealer", "dealer_self", "dealer_hedge", "total"
]


class MarketInstitutional(_Model):
    """Whole-market traded value of one institutional group on one day, in TWD."""

    market: Market
    trade_date: date
    investor: Investor
    buy_amount: Decimal = Field(ge=0)
    sell_amount: Decimal = Field(ge=0)
    net_amount: Decimal


class DistributionLevel(_Model):
    """One bracket of a stock's TDCC shareholding distribution (集保戶股權分散表)."""

    symbol: str
    week_date: date
    level: int = Field(ge=1, le=17)
    """1-15 = holding-size brackets, 16 = adjustment (差異數調整), 17 = total."""
    holders: int = Field(ge=0)
    shares: int = Field(ge=0)
    ratio: Decimal = Field(ge=0)
    """Fraction of TDCC custody (published as a percentage)."""


class Quote(_Model):
    """Intraday snapshot of one security."""

    symbol: str
    market: Market
    trade_date: date
    """Taipei trading date the snapshot belongs to."""
    at: AwareDatetime
    """Exchange time of the last update."""
    price: Decimal | None
    """Last trade; None when no trade has printed yet (or the feed omits it this tick)."""
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    prev_close: Decimal | None = None
    """Previous close / reference price the exchange measures today's change against."""
    volume: int = Field(ge=0, description="cumulative shares today")
    bid: Decimal | None = None
    ask: Decimal | None = None


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


class DelistingProvider(Provider):
    delisting_markets: ClassVar[frozenset[Market]]
    """Markets whose delisting list this source publishes."""

    @abstractmethod
    def fetch_delistings(self, market: Market, year: int) -> RawResponse: ...

    @abstractmethod
    def parse_delistings(self, raw: RawResponse) -> list[Delisting]:
        """Securities delisted during the requested year (may include market transfers)."""


class CorporateActionProvider(Provider):
    action_sources: ClassVar[dict[tuple[Market, ActionDataset], date]]
    """(market, dataset) pairs this source publishes, each with its first available date."""

    @abstractmethod
    def fetch_corporate_actions(
        self, market: Market, dataset: ActionDataset, start: date, end: date
    ) -> RawResponse:
        """Events dated in [start, end]; start is never before the dataset's first date."""

    @abstractmethod
    def parse_corporate_actions(self, raw: RawResponse) -> list[CorporateAction]: ...


class DividendDetailProvider(Provider):
    detail_markets: ClassVar[frozenset[Market]]
    detail_since: ClassVar[date]
    """First ex-date with a detail page (earlier event tables carry the parts themselves)."""

    @abstractmethod
    def fetch_dividend_detail(self, market: Market, symbol: str, ex_date: date) -> RawResponse: ...

    @abstractmethod
    def parse_dividend_detail(self, raw: RawResponse) -> list[DividendDetail]:
        """The event's parts, or an empty list when the source has no detail for it."""


class ExRightsPreviewProvider(Provider):
    preview_markets: ClassVar[frozenset[Market]]

    @abstractmethod
    def fetch_ex_rights_previews(self, market: Market) -> RawResponse:
        """The exchange's current 除權除息預告表 (a snapshot, no date parameter)."""

    @abstractmethod
    def parse_ex_rights_previews(self, raw: RawResponse) -> list[ExRightsPreview]: ...


class FinancialProvider(Provider):
    """Per-company statement history (one request per company and statement)."""

    @abstractmethod
    def fetch_financials(self, symbol: str, statement: Statement, start: date) -> RawResponse:
        """Every period of one statement from `start` on."""

    @abstractmethod
    def parse_financials(self, raw: RawResponse) -> list[FinancialItem]:
        """Items under canonical codes; unmapped source items are left in the raw object."""


class FinancialSnapshotProvider(Provider):
    """Whole-market snapshot of the latest filed quarter (official OpenAPI, as filed)."""

    snapshot_markets: ClassVar[frozenset[Market]]

    @abstractmethod
    def fetch_financial_snapshot(self, market: Market, statement: Statement) -> RawResponse: ...

    @abstractmethod
    def parse_financial_snapshot(self, raw: RawResponse) -> list[FinancialItem]: ...


class MonthlyRevenueProvider(Provider):
    """Per-company monthly revenue history."""

    @abstractmethod
    def fetch_monthly_revenue(self, symbol: str, start: date) -> RawResponse: ...

    @abstractmethod
    def parse_monthly_revenue(self, raw: RawResponse) -> list[MonthlyRevenue]: ...


class MonthlyRevenueSnapshotProvider(Provider):
    """Whole-market revenue of the latest published month."""

    revenue_markets: ClassVar[frozenset[Market]]

    @abstractmethod
    def fetch_monthly_revenue_snapshot(self, market: Market) -> RawResponse: ...

    @abstractmethod
    def parse_monthly_revenue_snapshot(self, raw: RawResponse) -> list[MonthlyRevenue]: ...


class CompanyProfileProvider(Provider):
    profile_markets: ClassVar[frozenset[Market]]

    @abstractmethod
    def fetch_company_profiles(self, market: Market) -> RawResponse: ...

    @abstractmethod
    def parse_company_profiles(self, raw: RawResponse) -> list[CompanyProfile]: ...


class InstitutionalTradeProvider(Provider):
    institutional_since: ClassVar[dict[Market, date]]
    """Markets served, each with the first date the source publishes."""

    @abstractmethod
    def fetch_institutional_trades(self, trade_date: date, market: Market) -> RawResponse: ...

    @abstractmethod
    def parse_institutional_trades(self, raw: RawResponse) -> list[InstitutionalTrade]:
        """Empty list = nothing published for that date (holiday, or not yet)."""


class MarginProvider(Provider):
    margin_since: ClassVar[dict[Market, date]]

    @abstractmethod
    def fetch_margin(self, trade_date: date, market: Market) -> RawResponse: ...

    @abstractmethod
    def parse_margin(self, raw: RawResponse) -> list[MarginTable]:
        """One table, or an empty list when nothing is published for that date."""


class ForeignHoldingProvider(Provider):
    foreign_holding_since: ClassVar[dict[Market, date]]

    @abstractmethod
    def fetch_foreign_holdings(self, trade_date: date, market: Market) -> RawResponse: ...

    @abstractmethod
    def parse_foreign_holdings(self, raw: RawResponse) -> list[ForeignHolding]: ...


class MarketInstitutionalProvider(Provider):
    market_institutional_since: ClassVar[dict[Market, date]]

    @abstractmethod
    def fetch_market_institutional(self, trade_date: date, market: Market) -> RawResponse: ...

    @abstractmethod
    def parse_market_institutional(self, raw: RawResponse) -> list[MarketInstitutional]: ...


class ShareholdingDistributionProvider(Provider):
    @abstractmethod
    def fetch_shareholding_distribution(self) -> RawResponse:
        """The latest published week (TDCC publishes no history)."""

    @abstractmethod
    def parse_shareholding_distribution(self, raw: RawResponse) -> list[DistributionLevel]: ...


class QuoteProvider(Provider):
    max_symbols: ClassVar[int] = 50
    """Largest batch one request may carry; callers split longer lists."""

    @abstractmethod
    def fetch_quotes(self, symbols: Sequence[tuple[str, Market]]) -> RawResponse:
        """Latest snapshot of each (symbol, market)."""

    @abstractmethod
    def parse_quotes(self, raw: RawResponse) -> list[Quote]: ...


INTERFACES: dict[DataKind, type[Provider]] = {
    "price": PriceProvider,
    "financial": FinancialProvider,
    "quote": QuoteProvider,
    "calendar": CalendarProvider,
    "securities": SecurityListProvider,
    "delistings": DelistingProvider,
    "corporate_actions": CorporateActionProvider,
    "dividend_details": DividendDetailProvider,
    "ex_rights_previews": ExRightsPreviewProvider,
    "financial_snapshot": FinancialSnapshotProvider,
    "monthly_revenue": MonthlyRevenueProvider,
    "monthly_revenue_snapshot": MonthlyRevenueSnapshotProvider,
    "company_profiles": CompanyProfileProvider,
    "institutional_trades": InstitutionalTradeProvider,
    "margin": MarginProvider,
    "foreign_holdings": ForeignHoldingProvider,
    "market_institutional": MarketInstitutionalProvider,
    "shareholding_distribution": ShareholdingDistributionProvider,
}
