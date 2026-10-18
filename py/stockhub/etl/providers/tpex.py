"""Taipei Exchange (official, OTC): daily closing quotes of every security for one date.

Endpoint: www/zh-tw/afterTrading/otc?type=EW (all securities except warrants), one request
per 3 s. Historical dates are supported; an empty table means no trading that day.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar

import httpx

from stockhub.etl.providers.base import (
    DailyBar,
    Market,
    PermanentProviderError,
    PriceProvider,
    RawResponse,
)
from stockhub.etl.providers.http import clean_number, get_json_bytes, make_client
from stockhub.etl.providers.registry import register_provider

OTC_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"


def _decimal(value: str | None) -> Decimal | None:
    text = clean_number(value)
    return Decimal(text) if text is not None else None


@register_provider
class TpexProvider(PriceProvider):
    name: ClassVar[str] = "tpex"
    min_interval: ClassVar[float] = 3.0
    markets: ClassVar[frozenset[Market]] = frozenset({"tpex"})

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or make_client()

    def fetch_daily_prices(self, trade_date: date, market: Market) -> RawResponse:
        if market != "tpex":
            raise PermanentProviderError(f"tpex does not serve {market} prices")
        params = {"date": f"{trade_date:%Y/%m/%d}", "type": "EW", "response": "json"}
        body = get_json_bytes(self.client, OTC_URL, params)
        return RawResponse("otc_quotes", body, {"date": trade_date.isoformat(), "market": market})

    def parse_daily_prices(self, raw: RawResponse) -> list[DailyBar]:
        payload: Any = raw.payload
        data = json.loads(payload) if isinstance(payload, bytes | str) else payload
        requested = date.fromisoformat(raw.params["date"])
        if str(data.get("stat", "")).lower() != "ok":
            raise ValueError(f"unexpected stat {data.get('stat')!r}")
        if data.get("date") != f"{requested:%Y%m%d}":
            raise ValueError(f"asked for {requested}, got data for {data.get('date')}")
        tables = data.get("tables") or []
        if not tables:
            raise ValueError("quote table not found")
        table = tables[0]
        # Header cells carry stray spaces ("收盤 ", " 成交金額(元)").
        col = {name.strip(): i for i, name in enumerate(table["fields"])}
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
