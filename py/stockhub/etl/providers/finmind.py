"""FinMind (finmindtrade.com): per-company statement and monthly revenue history.

FinMind aggregates MOPS filings; we use it for history because the official OpenAPI only
serves the latest quarter and MOPS itself disallows crawling (robots.txt). Daily updates come
from the official snapshots first; FinMind is asked only about companies that just filed.

Bases as published: the income statement is single-quarter (FinMind derives Q4 = year minus
Q1..Q3), the cash flow statement is year-to-date as filed, the balance sheet is a balance.
Values are TWD (EPS per share). Percent-of-assets items (`*_per`) are derived, so skipped.

Quota (free tier: 600 requests per hour per account): QuotaGuard paces requests, keeps a
rolling-hour count of its own, and asks the account's usage (user_info, which is not
counted) every few requests so another process sharing the token cannot push us over.
Hitting the limit anyway (HTTP 402) waits for the next hour instead of retrying.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar

import httpx

from stockhub.common.settings import get_settings
from stockhub.etl.providers.base import (
    Basis,
    FinancialItem,
    FinancialProvider,
    MonthlyRevenue,
    MonthlyRevenueProvider,
    PermanentProviderError,
    RawResponse,
    Statement,
    TransientProviderError,
)
from stockhub.etl.providers.http import TIMEOUT, USER_AGENT
from stockhub.etl.providers.registry import register_provider

log = logging.getLogger(__name__)

DATA_URL = "https://api.finmindtrade.com/api/v4/data"
USER_INFO_URL = "https://api.web.finmindtrade.com/v2/user_info"

DATASETS: dict[Statement, str] = {
    "IS": "TaiwanStockFinancialStatements",
    "BS": "TaiwanStockBalanceSheet",
    "CF": "TaiwanStockCashFlowsStatement",
}
REVENUE_DATASET = "TaiwanStockMonthRevenue"
BASIS: dict[Statement, Basis] = {"IS": "quarter", "BS": "instant", "CF": "ytd"}

# FinMind `type` -> canonical item code (financial_item_map, industry_type 'general').
ITEMS: dict[Statement, dict[str, str]] = {
    "IS": {
        "Revenue": "Revenue",
        "CostOfGoodsSold": "CostOfRevenue",
        "GrossProfit": "GrossProfit",
        "OperatingExpenses": "OperatingExpenses",
        "OperatingIncome": "OperatingIncome",
        "TotalNonoperatingIncomeAndExpense": "NonOperatingIncome",
        "PreTaxIncome": "PreTaxIncome",
        "TAX": "IncomeTax",
        "IncomeAfterTaxes": "NetIncome",
        "EquityAttributableToOwnersOfParent": "NetIncomeParent",
        "NoncontrollingInterests": "NetIncomeNCI",
        "OtherComprehensiveIncome": "OtherComprehensiveIncome",
        "TotalConsolidatedProfitForThePeriod": "ComprehensiveIncome",
        "EPS": "EPS",
    },
    "BS": {
        "TotalAssets": "TotalAssets",
        "CurrentAssets": "CurrentAssets",
        "NoncurrentAssets": "NoncurrentAssets",
        "CashAndCashEquivalents": "Cash",
        "AccountsReceivableNet": "AccountsReceivable",
        "Inventories": "Inventories",
        "PropertyPlantAndEquipment": "PropertyPlantEquipment",
        "Liabilities": "TotalLiabilities",
        "CurrentLiabilities": "CurrentLiabilities",
        "NoncurrentLiabilities": "NoncurrentLiabilities",
        "ShorttermBorrowings": "ShortTermBorrowings",
        "LongtermBorrowings": "LongTermBorrowings",
        "BondsPayable": "BondsPayable",
        "CapitalStock": "CapitalStock",
        "OrdinaryShare": "OrdinaryShare",
        "RetainedEarnings": "RetainedEarnings",
        "EquityAttributableToOwnersOfParent": "EquityParent",
        "NoncontrollingInterests": "EquityNCI",
        "Equity": "TotalEquity",
    },
    "CF": {
        "CashFlowsFromOperatingActivities": "OperatingCashFlow",
        "CashProvidedByInvestingActivities": "InvestingCashFlow",
        "CashFlowsProvidedFromFinancingActivities": "FinancingCashFlow",
        "PropertyAndPlantAndEquipment": "CapitalExpenditure",
        "Depreciation": "Depreciation",
        "AmortizationExpense": "Amortization",
    },
}

QUARTER_ENDS = {(3, 31), (6, 30), (9, 30), (12, 31)}
ANONYMOUS_PER_HOUR = 250
"""Ceiling without a token (FinMind allows 300 per hour per IP)."""
LIMIT_STATUS = 402
"""FinMind's status for 'requests reach the upper limit'."""


class QuotaGuard:
    """Keeps this process (and, via the account usage, every process) under `per_hour`."""

    def __init__(
        self,
        per_hour: int,
        usage: Callable[[], tuple[int, int] | None],
        *,
        check_every: int = 25,
        wait_step: float = 300.0,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.per_hour = per_hour
        self._usage = usage
        self._check_every = check_every
        self._wait_step = wait_step
        self._clock, self._sleep = clock, sleep
        self._window: deque[float] = deque()
        self._since_check: int | None = None

    def acquire(self) -> None:
        """Block until one more request fits; call right before each data request."""
        now = self._clock()
        while self._window and self._window[0] <= now - 3600:
            self._window.popleft()
        if len(self._window) >= self.per_hour:
            wait = self._window[0] + 3600 - now
            log.warning(
                "FinMind: %d requests in the last hour; waiting %.0f s", self.per_hour, wait
            )
            self._sleep(wait)
        if self._since_check is None or self._since_check >= self._check_every:
            self._since_check = 0
            self._wait_for_account()
        self._since_check += 1
        self._window.append(self._clock())

    def _wait_for_account(self) -> None:
        while True:
            usage = self._usage()
            if usage is None:  # no token, or user_info unreachable: rely on our own count
                return
            used, limit = usage
            cap = min(self.per_hour, int(limit * 0.9))
            if used < cap:
                return
            log.warning("FinMind account used %d of %d this hour; waiting", used, limit)
            self._sleep(self._wait_step)

    def wait_for_reset(self) -> None:
        """After an HTTP 402: sleep to one minute past the next full hour."""
        now = self._clock()
        wait = 3600 - now % 3600 + 60
        log.warning("FinMind request limit reached; waiting %.0f s", wait)
        self._sleep(wait)
        self._since_check = None


def _loads(payload: bytes | str | Any) -> Any:
    if isinstance(payload, bytes | str):
        return json.loads(payload, parse_float=Decimal)
    return payload


def _quarter_end(text: str) -> date | None:
    day = date.fromisoformat(text)
    return day if (day.month, day.day) in QUARTER_ENDS else None


@register_provider
class FinMindProvider(FinancialProvider, MonthlyRevenueProvider):
    name: ClassVar[str] = "finmind"
    min_interval: ClassVar[float] = 7.2
    """3600 / 7.2 = 500 requests per hour at most from one process."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        token: str | None = None,
        guard: QuotaGuard | None = None,
    ) -> None:
        settings = None
        if token is None or guard is None:
            settings = get_settings()
        if token is None and settings is not None and settings.finmind_token is not None:
            token = settings.finmind_token.get_secret_value()
        self.token = token
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=TIMEOUT,
            follow_redirects=True,
        )
        if guard is None:
            per_hour = settings.finmind_requests_per_hour if settings else 500
            guard = QuotaGuard(per_hour if token else min(per_hour, ANONYMOUS_PER_HOUR), self.usage)
        self.guard = guard

    # ------------------------------------------------------------------ plumbing

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def usage(self) -> tuple[int, int] | None:
        """(requests used this hour, hourly limit) of the token's account; None if unknown."""
        if not self.token:
            return None
        try:
            response = self.client.get(USER_INFO_URL, headers=self._headers)
            info = response.json()
            return int(info["user_count"]), int(info["api_request_limit_hour"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.warning("FinMind user_info failed: %s", exc)
            return None

    def _get(self, dataset: str, symbol: str, start: date) -> bytes:
        params = {"dataset": dataset, "data_id": symbol, "start_date": start.isoformat()}
        for attempt in (1, 2):
            self.guard.acquire()
            try:
                response = self.client.get(DATA_URL, params=params, headers=self._headers)
            except httpx.TimeoutException as exc:
                raise TransientProviderError(f"timeout: FinMind {dataset} {symbol}") from exc
            except httpx.TransportError as exc:
                raise TransientProviderError(f"network error: {exc}") from exc
            status = response.status_code
            body = response.content
            if status == 200:
                try:
                    status = int(json.loads(body).get("status", 200))
                except (ValueError, AttributeError) as exc:
                    raise TransientProviderError("FinMind returned non-JSON") from exc
            if status == LIMIT_STATUS:
                if attempt == 1:
                    self.guard.wait_for_reset()
                    continue
                raise TransientProviderError("FinMind request limit still reached")
            if status == 429 or status >= 500:
                raise TransientProviderError(f"FinMind HTTP {status} for {dataset} {symbol}")
            if status >= 400:
                message = response.text[:200]
                raise PermanentProviderError(f"FinMind {status} for {dataset} {symbol}: {message}")
            return body
        raise AssertionError("unreachable")  # pragma: no cover

    # ------------------------------------------------------------------ statements

    def fetch_financials(self, symbol: str, statement: Statement, start: date) -> RawResponse:
        body = self._get(DATASETS[statement], symbol, start)
        params = {"symbol": symbol, "statement": statement, "start": start.isoformat()}
        return RawResponse(DATASETS[statement], body, params)

    def parse_financials(self, raw: RawResponse) -> list[FinancialItem]:
        statement: Statement = raw.params["statement"]
        mapping = ITEMS[statement]
        data = _loads(raw.payload)
        if data.get("msg") != "success":
            raise ValueError(f"FinMind {raw.dataset}: {data.get('msg')!r}")
        items: dict[tuple[date, str], FinancialItem] = {}
        for row in data["data"]:
            code = mapping.get(row["type"])
            period_end = _quarter_end(row["date"])
            if code is None or period_end is None or row["value"] is None:
                continue
            items[(period_end, code)] = FinancialItem(
                symbol=row["stock_id"],
                period_end=period_end,
                statement=statement,
                item_code=code,
                value=Decimal(row["value"]),
                basis=BASIS[statement],
            )
        return sorted(items.values(), key=lambda i: (i.period_end, i.item_code))

    # ------------------------------------------------------------------ monthly revenue

    def fetch_monthly_revenue(self, symbol: str, start: date) -> RawResponse:
        # FinMind filters on `date`, the month after the revenue month: a start of 2013-01-01
        # also returns December 2012.
        body = self._get(REVENUE_DATASET, symbol, start)
        return RawResponse(REVENUE_DATASET, body, {"symbol": symbol, "start": start.isoformat()})

    def parse_monthly_revenue(self, raw: RawResponse) -> list[MonthlyRevenue]:
        data = _loads(raw.payload)
        if data.get("msg") != "success":
            raise ValueError(f"FinMind {raw.dataset}: {data.get('msg')!r}")
        months: dict[date, MonthlyRevenue] = {}
        for row in data["data"]:
            month = date(int(row["revenue_year"]), int(row["revenue_month"]), 1)
            created = (row.get("create_time") or "").strip()
            months[month] = MonthlyRevenue(
                symbol=row["stock_id"],
                revenue_month=month,
                revenue=Decimal(row["revenue"]),
                publish_date=date.fromisoformat(created[:10]) if created else None,
            )
        return sorted(months.values(), key=lambda m: m.revenue_month)
