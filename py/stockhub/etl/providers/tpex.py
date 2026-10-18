"""Taipei Exchange (official, OTC): daily closing quotes of every security for one date.

Endpoint: www/zh-tw/afterTrading/otc?type=EW (all securities except warrants), one request
per 3 s. History starts on 2007-07-02 (earlier dates return an empty table, like holidays).
Also company/deListed: OTC companies delisted in a year, including transfers to TWSE.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar

import httpx

from stockhub.etl.providers.base import (
    DailyBar,
    Delisting,
    DelistingProvider,
    Market,
    PermanentProviderError,
    PriceProvider,
    RawResponse,
)
from stockhub.etl.providers.http import clean_number, get_json_bytes, make_client, roc_date
from stockhub.etl.providers.registry import register_provider

OTC_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"
DELISTED_URL = "https://www.tpex.org.tw/www/zh-tw/company/deListed"


def _decimal(value: str | None) -> Decimal | None:
    text = clean_number(value)
    return Decimal(text) if text is not None else None


def _loads(payload: Any) -> Any:
    return json.loads(payload) if isinstance(payload, bytes | str) else payload


def _first_table(data: Any) -> dict[str, Any]:
    if str(data.get("stat", "")).lower() != "ok":
        raise ValueError(f"unexpected stat {data.get('stat')!r}")
    tables = data.get("tables") or []
    if not tables:
        raise ValueError("table not found")
    table: dict[str, Any] = tables[0]
    return table


def _columns(table: dict[str, Any]) -> dict[str, int]:
    # Header cells carry stray spaces ("收盤 ", " 成交金額(元)").
    return {name.strip(): i for i, name in enumerate(table["fields"])}


@register_provider
class TpexProvider(PriceProvider, DelistingProvider):
    name: ClassVar[str] = "tpex"
    min_interval: ClassVar[float] = 3.0
    markets: ClassVar[frozenset[Market]] = frozenset({"tpex"})
    delisting_markets: ClassVar[frozenset[Market]] = frozenset({"tpex"})

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or make_client()

    def fetch_daily_prices(self, trade_date: date, market: Market) -> RawResponse:
        if market != "tpex":
            raise PermanentProviderError(f"tpex does not serve {market} prices")
        params = {"date": f"{trade_date:%Y/%m/%d}", "type": "EW", "response": "json"}
        body = get_json_bytes(self.client, OTC_URL, params)
        return RawResponse("otc_quotes", body, {"date": trade_date.isoformat(), "market": market})

    def parse_daily_prices(self, raw: RawResponse) -> list[DailyBar]:
        data = _loads(raw.payload)
        requested = date.fromisoformat(raw.params["date"])
        table = _first_table(data)
        if data.get("date") != f"{requested:%Y%m%d}":
            raise ValueError(f"asked for {requested}, got data for {data.get('date')}")
        col = _columns(table)
        bars = []
        for row in table.get("data") or []:
            volume = clean_number(row[col["成交股數"]])
            turnover = clean_number(row[col["成交金額(元)"]])
            bars.append(
                DailyBar(
                    symbol=row[col["代號"]].strip(),
                    trade_date=requested,
                    open=_decimal(row[col["開盤"]]),
                    high=_decimal(row[col["最高"]]),
                    low=_decimal(row[col["最低"]]),
                    close=_decimal(row[col["收盤"]]),
                    volume=int(volume or 0),
                    turnover=Decimal(turnover or 0),
                )
            )
        return bars

    # ------------------------------------------------------------------ delistings

    def fetch_delistings(self, market: Market, year: int) -> RawResponse:
        if market != "tpex":
            raise PermanentProviderError(f"tpex does not publish {market} delistings")
        body = get_json_bytes(self.client, DELISTED_URL, {"date": str(year), "response": "json"})
        return RawResponse("delisted", body, {"year": year, "market": market})

    def parse_delistings(self, raw: RawResponse) -> list[Delisting]:
        table = _first_table(_loads(raw.payload))
        col = _columns(table)
        year = int(raw.params["year"])
        out = []
        for row in table.get("data") or []:
            symbol = row[col["股票代號"]].strip()
            day = roc_date(row[col["終止上櫃日期"]])
            if day.year != year or not (len(symbol) == 4 and symbol.isdigit()):
                continue
            out.append(
                Delisting(
                    symbol=symbol,
                    name=row[col["公司名稱"]].strip().removesuffix("股份有限公司"),
                    market="tpex",
                    delisted_date=day,
                    reason=row[col["終止上櫃原因"]].strip() or None,
                )
            )
        return out
