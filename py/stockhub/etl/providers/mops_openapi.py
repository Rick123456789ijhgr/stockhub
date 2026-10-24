"""Parsers for the MOPS datasets both exchanges republish on their official OpenAPI.

TWSE (openapi.twse.com.tw/v1/opendata/...) and TPEx (www.tpex.org.tw/openapi/v1/mopsfin_...)
serve the same tables with slightly different keys (TPEx mixes English and Chinese):

- t187ap06_*_ci  income statement of general companies, latest filed quarter, year-to-date
- t187ap07_*_ci  balance sheet of general companies, latest filed quarter
- t187ap05_*     monthly revenue of the latest published month
- t187ap03_*     company profile (industry code, par value, issued shares)
- t187ap04_*     today's 重大訊息 (material announcements), a snapshot of the day so far

Amounts are in thousands of TWD; per-share items are in TWD. Each row carries its own
year and quarter (ROC calendar). The other statement templates (_basi, _bd, _fh, _ins, _mim)
belong to financial companies (M3b).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, ClassVar

import httpx

from stockhub.common.timeutil import TAIPEI
from stockhub.engine.news import clip, one_line
from stockhub.etl.providers.base import (
    CompanyProfile,
    CompanyProfileProvider,
    FinancialItem,
    FinancialSnapshotProvider,
    Market,
    MonthlyRevenue,
    MonthlyRevenueSnapshotProvider,
    NewsItem,
    NewsKind,
    NewsProvider,
    NewsRequest,
    PermanentProviderError,
    RawResponse,
    Statement,
)
from stockhub.etl.providers.http import get_json_bytes, maybe_decimal, roc_date

THOUSAND = Decimal(1000)

IS_COLUMNS = {
    "營業收入": "Revenue",
    "營業成本": "CostOfRevenue",
    "營業毛利（毛損）淨額": "GrossProfit",
    "營業費用": "OperatingExpenses",
    "營業利益（損失）": "OperatingIncome",
    "營業外收入及支出": "NonOperatingIncome",
    "稅前淨利（淨損）": "PreTaxIncome",
    "所得稅費用（利益）": "IncomeTax",
    "本期淨利（淨損）": "NetIncome",
    "淨利（淨損）歸屬於母公司業主": "NetIncomeParent",
    "淨利（淨損）歸屬於非控制權益": "NetIncomeNCI",
    "其他綜合損益（淨額）": "OtherComprehensiveIncome",
    "本期綜合損益總額": "ComprehensiveIncome",
    "基本每股盈餘（元）": "EPS",
}
BS_COLUMNS = {
    "流動資產": "CurrentAssets",
    "非流動資產": "NoncurrentAssets",
    "資產總計": "TotalAssets",
    "流動負債": "CurrentLiabilities",
    "非流動負債": "NoncurrentLiabilities",
    "負債總計": "TotalLiabilities",
    "股本": "CapitalStock",
    "保留盈餘": "RetainedEarnings",
    "歸屬於母公司業主之權益合計": "EquityParent",
    "非控制權益": "EquityNCI",
    "權益總計": "TotalEquity",
    "每股參考淨值": "BookValuePerShare",
}
COLUMNS: dict[Statement, dict[str, str]] = {"IS": IS_COLUMNS, "BS": BS_COLUMNS}
PER_SHARE = {"EPS", "BookValuePerShare"}
QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}

SYMBOL_KEYS = ("公司代號", "SecuritiesCompanyCode")
YEAR_KEYS = ("年度", "Year")
QUARTER_KEYS = ("季別", "Season")


def loads(payload: bytes | str | Any) -> list[dict[str, Any]]:
    rows = json.loads(payload) if isinstance(payload, bytes | str) else payload
    if not isinstance(rows, list):
        raise ValueError("expected a JSON array")
    return rows


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    raise ValueError(f"row has none of {keys}")


def quarter_end(roc_year: str, quarter: str) -> date:
    month, day = QUARTER_END[int(quarter)]
    return date(int(roc_year) + 1911, month, day)


def parse_statement(rows: list[dict[str, Any]], statement: Statement) -> list[FinancialItem]:
    columns = COLUMNS[statement]
    items = []
    for row in rows:
        symbol = _first(row, SYMBOL_KEYS)
        period_end = quarter_end(_first(row, YEAR_KEYS), _first(row, QUARTER_KEYS))
        for column, code in columns.items():
            value = maybe_decimal(row.get(column))
            if value is None:
                continue
            items.append(
                FinancialItem(
                    symbol=symbol,
                    period_end=period_end,
                    statement=statement,
                    item_code=code,
                    value=value if code in PER_SHARE else value * THOUSAND,
                    basis="ytd" if statement == "IS" else "instant",
                )
            )
    return items


def parse_monthly_revenue(rows: list[dict[str, Any]]) -> list[MonthlyRevenue]:
    out = []
    for row in rows:
        revenue = maybe_decimal(row.get("營業收入-當月營收"))
        if revenue is None:
            continue
        period = _first(row, ("資料年月",))  # e.g. 11509
        out.append(
            MonthlyRevenue(
                symbol=_first(row, SYMBOL_KEYS),
                revenue_month=date(int(period[:-2]) + 1911, int(period[-2:]), 1),
                revenue=revenue * THOUSAND,
            )
        )
    return out


_TWD = re.compile(r"新台幣\s*([\d.,]+)\s*元")


def par_value(text: str | None) -> Decimal | None:
    """'新台幣                 10.0000元' -> 10; other currencies (some KY companies) -> None."""
    match = _TWD.search(text or "")
    if not match:
        return None
    value = maybe_decimal(match.group(1))
    return value if value and value > 0 else None


def parse_company_profiles(rows: list[dict[str, Any]], market: Market) -> list[CompanyProfile]:
    out = []
    for row in rows:
        shares = maybe_decimal(row.get("已發行普通股數或TDR原股發行股數") or row.get("IssueShares"))
        code = (row.get("產業別") or row.get("SecuritiesIndustryCode") or "").strip()
        out.append(
            CompanyProfile(
                symbol=_first(row, SYMBOL_KEYS),
                market=market,
                industry_code=code or None,
                par_value=par_value(row.get("普通股每股面額") or row.get("ParValueOfCommonStock")),
                issued_shares=int(shares) if shares is not None and shares >= 0 else None,
            )
        )
    return out


MOPS_LINK = "https://mops.twse.com.tw/mops/#/web/t05st01?companyId={symbol}"
"""Where a person reads a company's announcements (the OpenAPI rows carry no link)."""


def _announcement_time(day: str, clock: str) -> datetime:
    """發言日期 '1151021' + 發言時間 '70004' (HHMMSS without the leading zero) in Taipei."""
    digits = clock.strip().zfill(6)
    at = time(int(digits[:2]), int(digits[2:4]), int(digits[4:6]))
    return datetime.combine(roc_date(day), at, TAIPEI)


def parse_announcements(rows: list[dict[str, Any]], market: Market) -> list[NewsItem]:
    """Rows of t187ap04_L / mopsfin_t187ap04_O (keys differ slightly; TWSE writes '主旨 ')."""
    out = []
    for raw_row in rows:
        row = {str(k).strip(): v for k, v in raw_row.items()}
        symbol = _first(row, SYMBOL_KEYS)
        subject = one_line(str(row.get("主旨") or ""))
        if not subject:
            continue
        day, clock = str(row["發言日期"]), str(row["發言時間"])
        lines = str(row.get("說明") or "").replace("\r\n", "\n").split("\n")
        detail = "\n".join(line.strip() for line in lines).strip()
        digest = hashlib.sha1(subject.encode(), usedforsecurity=False).hexdigest()[:8]
        fact = str(row.get("事實發生日") or "").strip()
        out.append(
            NewsItem(
                external_id=f"{symbol}-{day.strip()}-{clock.strip()}-{digest}",
                url=MOPS_LINK.format(symbol=symbol),
                title=subject,
                snippet=clip(detail),
                published_at=_announcement_time(day, clock),
                symbols=[symbol],
                meta={
                    "market": market,
                    "company": str(row.get("公司名稱") or row.get("CompanyName") or "").strip(),
                    "clause": str(row.get("符合條款") or "").strip() or None,
                    "factDate": roc_date(fact).isoformat() if fact.isdigit() else None,
                },
                body=f"{subject}\n{detail}" if detail else subject,
            )
        )
    return out


class MopsOpenApiMixin(
    FinancialSnapshotProvider, MonthlyRevenueSnapshotProvider, CompanyProfileProvider, NewsProvider
):
    """The snapshot capabilities and the day's 重大訊息, for an exchange adapter that sets the
    class vars."""

    mops_market: ClassVar[Market]
    mops_urls: ClassVar[dict[str, str]]
    """Keys IS, BS, revenue, profiles, announcements -> endpoint URL."""
    news_kinds: ClassVar[frozenset[NewsKind]] = frozenset({"mops"})
    client: httpx.Client

    def _mops_get(self, market: Market, key: str) -> RawResponse:
        if market != self.mops_market:
            raise PermanentProviderError(f"{self.name} does not publish {market} {key}")
        url = self.mops_urls[key]
        body = get_json_bytes(self.client, url)
        return RawResponse(url.rsplit("/", 1)[-1].lower(), body, {"market": market, "kind": key})

    def fetch_financial_snapshot(self, market: Market, statement: Statement) -> RawResponse:
        if statement not in COLUMNS:
            raise PermanentProviderError(f"no {statement} snapshot on the OpenAPI")
        return self._mops_get(market, statement)

    def parse_financial_snapshot(self, raw: RawResponse) -> list[FinancialItem]:
        return parse_statement(loads(raw.payload), raw.params["kind"])

    def fetch_monthly_revenue_snapshot(self, market: Market) -> RawResponse:
        return self._mops_get(market, "revenue")

    def parse_monthly_revenue_snapshot(self, raw: RawResponse) -> list[MonthlyRevenue]:
        return parse_monthly_revenue(loads(raw.payload))

    def fetch_company_profiles(self, market: Market) -> RawResponse:
        return self._mops_get(market, "profiles")

    def parse_company_profiles(self, raw: RawResponse) -> list[CompanyProfile]:
        return parse_company_profiles(loads(raw.payload), raw.params["market"])

    def serves(self, request: NewsRequest) -> bool:
        return request.kind == "mops" and request.market == self.mops_market

    def fetch_news(self, request: NewsRequest) -> RawResponse:
        if request.market is None:
            raise PermanentProviderError("a mops source needs its market")
        response = self._mops_get(request.market, "announcements")
        return RawResponse(
            response.dataset, response.payload, {**response.params, "source": request.source}
        )

    def parse_news(self, raw: RawResponse) -> list[NewsItem]:
        return parse_announcements(loads(raw.payload), raw.params["market"])
