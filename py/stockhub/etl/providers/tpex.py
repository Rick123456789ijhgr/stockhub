"""Taipei Exchange (official, OTC): daily closing quotes of every security for one date.

Endpoint: www/zh-tw/afterTrading/otc?type=EW (all securities except warrants), one request
per 3 s. History starts on 2007-07-02 (earlier dates return an empty table, like holidays).
Also company/deListed: OTC companies delisted in a year, including transfers to TWSE;
bulletin/exDailyQ and bulletin/revivt: ex-rights/dividend results (from late 2007) and
capital reductions (from 2013) with the exchange's reference prices.
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar

import httpx

from stockhub.etl.providers.base import (
    ActionDataset,
    ActionType,
    CorporateAction,
    CorporateActionProvider,
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
class TpexProvider(PriceProvider, DelistingProvider, CorporateActionProvider):
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
            volume = int(clean_number(row[col["成交股數"]]) or 0)
            turnover = clean_number(row[col["成交金額(元)"]])
            ohlc = [_decimal(row[col[c]]) for c in ("開盤", "最高", "最低", "收盤")]
            if volume == 0 and all(p is not None and p == 0 for p in ohlc):
                # Until 2011-11 the table printed 0.00 for a day without trades (now "----").
                ohlc = [None, None, None, None]
            bars.append(
                DailyBar(
                    symbol=row[col["代號"]].strip(),
                    trade_date=requested,
                    open=ohlc[0],
                    high=ohlc[1],
                    low=ohlc[2],
                    close=ohlc[3],
                    volume=volume,
                    turnover=Decimal(turnover or 0),
                    name=row[col["名稱"]].strip() or None,
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

    # ------------------------------------------------------------------ corporate actions

    action_sources: ClassVar[dict[tuple[Market, ActionDataset], date]] = {
        ("tpex", "dividend"): date(2007, 7, 1),
        ("tpex", "capital_reduction"): date(2013, 1, 1),
    }
    # Par-value changes and ETF splits have no historical table on the new TPEx site; the
    # adjustment job flags the resulting price gaps instead (DECISIONS D-053).

    def fetch_corporate_actions(
        self, market: Market, dataset: ActionDataset, start: date, end: date
    ) -> RawResponse:
        if (market, dataset) not in self.action_sources:
            raise PermanentProviderError(f"tpex does not publish {market} {dataset}")
        params = {
            "startDate": f"{start:%Y/%m/%d}",
            "endDate": f"{end:%Y/%m/%d}",
            "response": "json",
        }
        body = get_json_bytes(self.client, ACTION_URLS[dataset], params)
        return RawResponse(
            f"actions_{dataset}",
            body,
            {
                "market": market,
                "dataset": dataset,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )

    def parse_corporate_actions(self, raw: RawResponse) -> list[CorporateAction]:
        table = _first_table(_loads(raw.payload))
        col = _columns(table)
        parse_row = _dividend_row if raw.params["dataset"] == "dividend" else _reduction_row
        out = []
        for row in table.get("data") or []:
            action = parse_row({name: str(row[i]).strip() for name, i in col.items()})
            if action is not None:
                out.append(action)
        return out


ACTION_URLS: dict[str, str] = {
    "dividend": "https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ",
    "capital_reduction": "https://www.tpex.org.tw/www/zh-tw/bulletin/revivt",
}
DIVIDEND_TYPES: dict[str, ActionType] = {
    "除息": "cash_dividend",
    "除權": "stock_dividend",
    "除權息": "cash_and_stock_dividend",
}
THOUSAND = Decimal(1000)


def _in_scope(symbol: str) -> bool:
    return (len(symbol) == 4 and symbol.isdigit()) or symbol.startswith("00")


def _dividend_row(cells: dict[str, str]) -> CorporateAction | None:
    symbol = cells["代號"]
    kind = DIVIDEND_TYPES.get(cells["權/息"])
    if kind is None or not _in_scope(symbol):
        return None
    per_thousand = _decimal(cells.get("每仟股無償配股"))
    subscription = _decimal(cells.get("現金增資認購價"))
    cash = _decimal(cells.get("現金股利"))
    if kind == "stock_dividend" and subscription and not per_thousand and not cash:
        # 除權 with only a cash capital increase: a rights offering, whose reference price
        # rises when the subscription price is above the market.
        kind = "rights_issue"
    return CorporateAction(
        symbol=symbol,
        market="tpex",
        ex_date=roc_date(cells["除權息日期"]),
        action_type=kind,
        prev_close=_decimal(cells["除權息前收盤價"]),
        reference_price=_decimal(cells["除權息參考價"]),
        cash_dividend=cash,
        stock_dividend_ratio=per_thousand / THOUSAND if per_thousand else None,
    )


_DETAIL_NUMBER = r"{label}:</th><td>([\d.,]+)"


def _detail_number(html: str, label: str) -> Decimal | None:
    match = re.search(_DETAIL_NUMBER.format(label=re.escape(label)), html)
    return _decimal(match.group(1)) if match else None


def _reduction_row(cells: dict[str, str]) -> CorporateAction | None:
    symbol = cells["股票代號"]
    if not _in_scope(symbol):
        return None
    detail = cells.get("詳細資料", "")
    new_shares = _detail_number(detail, "每壹仟股換發新股票")
    refund = _detail_number(detail, "每股退還股款")
    return CorporateAction(
        symbol=symbol,
        market="tpex",
        ex_date=roc_date(cells["恢復買賣日期"]),
        action_type="capital_reduction",
        prev_close=_decimal(cells["最後交易日之收盤價格"]),
        reference_price=_decimal(cells["減資恢復買賣開始日參考價格"]),
        cash_dividend=refund or None,
        ratio=new_shares / THOUSAND if new_shares else None,
    )
