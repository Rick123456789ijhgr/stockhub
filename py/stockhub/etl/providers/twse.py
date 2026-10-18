"""Taiwan Stock Exchange (official): daily quotes, holiday schedule, ISIN master lists.

Endpoints (robots.txt allows them; we stay at one request per 3 s):
- MI_INDEX?type=ALLBUT0999  every listed security's daily quote for one date (since 2004)
- holidaySchedule           announced holidays of a year (published from 2021)
- isin.twse.com.tw          master list with listing dates, for TWSE (strMode=2) and TPEx (4)
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any, ClassVar

import httpx

from stockhub.etl.providers.base import (
    CalendarEntry,
    CalendarProvider,
    DailyBar,
    Market,
    PermanentProviderError,
    PriceProvider,
    RawResponse,
    Security,
    SecurityListProvider,
)
from stockhub.etl.providers.http import clean_number, get_bytes, get_json_bytes, make_client
from stockhub.etl.providers.registry import register_provider

MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
HOLIDAY_URL = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule"
ISIN_URL = "https://isin.twse.com.tw/isin/C_public.jsp"
ISIN_MODES: dict[Market, int] = {"twse": 2, "tpex": 4}

NO_DATA = "沒有符合條件的資料"
# ISIN sections we keep; warrants, ETNs, TDRs, preferred shares and REITs are out of scope.
ISIN_SECTIONS = {"股票": "stock", "創新板": "stock", "ETF": "etf"}


def _loads(payload: bytes | str | Any) -> Any:
    return json.loads(payload) if isinstance(payload, bytes | str) else payload


def _decimal(value: str | None) -> Decimal | None:
    text = clean_number(value)
    return Decimal(text) if text is not None else None


@register_provider
class TwseProvider(PriceProvider, CalendarProvider, SecurityListProvider):
    name: ClassVar[str] = "twse"
    min_interval: ClassVar[float] = 3.0
    markets: ClassVar[frozenset[Market]] = frozenset({"twse"})
    security_markets: ClassVar[frozenset[Market]] = frozenset({"twse", "tpex"})

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or make_client()

    # ------------------------------------------------------------------ daily quotes

    def fetch_daily_prices(self, trade_date: date, market: Market) -> RawResponse:
        if market != "twse":
            raise PermanentProviderError(f"twse does not serve {market} prices")
        params = {"date": f"{trade_date:%Y%m%d}", "type": "ALLBUT0999", "response": "json"}
        body = get_json_bytes(self.client, MI_INDEX_URL, params)
        return RawResponse("mi_index", body, {"date": trade_date.isoformat(), "market": market})

    def parse_daily_prices(self, raw: RawResponse) -> list[DailyBar]:
        data = _loads(raw.payload)
        requested = date.fromisoformat(raw.params["date"])
        stat = str(data.get("stat", ""))
        if NO_DATA in stat:
            return []
        if stat != "OK":
            raise ValueError(f"unexpected stat {stat!r}")
        if data.get("date") != f"{requested:%Y%m%d}":
            raise ValueError(f"asked for {requested}, got data for {data.get('date')}")
        table = next(
            (t for t in data.get("tables", []) if "證券代號" in (t.get("fields") or [])), None
        )
        if table is None:
            raise ValueError("daily quote table not found")
        col = {name: i for i, name in enumerate(table["fields"])}
        bars = []
        for row in table["data"]:
            volume = clean_number(row[col["成交股數"]])
            turnover = clean_number(row[col["成交金額"]])
            bars.append(
                DailyBar(
                    symbol=row[col["證券代號"]].strip(),
                    trade_date=requested,
                    open=_decimal(row[col["開盤價"]]),
                    high=_decimal(row[col["最高價"]]),
                    low=_decimal(row[col["最低價"]]),
                    close=_decimal(row[col["收盤價"]]),
                    volume=int(volume or 0),
                    turnover=Decimal(turnover or 0),
                )
            )
        return bars

    # ------------------------------------------------------------------ holidays

    def fetch_calendar(self, year: int) -> RawResponse:
        params = {"date": f"{year}0101", "response": "json"}
        body = get_json_bytes(self.client, HOLIDAY_URL, params)
        return RawResponse("holiday_schedule", body, {"year": year})

    def parse_calendar(self, raw: RawResponse) -> list[CalendarEntry]:
        data = _loads(raw.payload)
        if data.get("stat") != "ok":
            raise ValueError(f"unexpected stat {data.get('stat')!r}")
        entries = []
        for day_text, name, *_ in data.get("data", []):
            label = name.strip()
            # "...開始交易日" / "...最後交易日" are announced trading days; everything else
            # (holidays, "市場無交易，僅辦理結算交割作業") means the market is closed.
            trading = "開始交易" in label or "最後交易" in label
            entries.append(
                CalendarEntry(day=date.fromisoformat(day_text), name=label, is_trading_day=trading)
            )
        return entries

    # ------------------------------------------------------------------ master list

    def fetch_securities(self, market: Market) -> RawResponse:
        body = get_bytes(self.client, ISIN_URL, {"strMode": ISIN_MODES[market]})
        if b"bgcolor=#FAFAD2" not in body:
            raise PermanentProviderError("ISIN page has no security rows")
        return RawResponse("isin", body, {"market": market})

    def parse_securities(self, raw: RawResponse) -> list[Security]:
        payload = raw.payload
        html = payload.decode("cp950", "replace") if isinstance(payload, bytes) else str(payload)
        market: Market = raw.params["market"]
        securities = []
        for section, cells in _isin_rows(html):
            kind = ISIN_SECTIONS.get(section)
            if kind is None or len(cells) < 5:
                continue
            symbol, _, name = cells[0].partition("　")
            try:
                year, month, day = (int(part) for part in cells[2].split("/"))
                listed = date(year, month, day)
            except ValueError:
                continue
            securities.append(
                Security(
                    symbol=symbol.strip(),
                    name=name.strip(),
                    market=market,
                    type="etf" if kind == "etf" else "stock",
                    listed_date=listed,
                    industry=cells[4] or None,
                    isin=cells[1] or None,
                )
            )
        if not securities:
            raise ValueError("no securities parsed from ISIN page")
        return securities


class _IsinTableParser(HTMLParser):
    """Collects table rows as lists of cell texts."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._row is not None and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _isin_rows(html: str) -> list[tuple[str, list[str]]]:
    """(section title, cells) for each data row; single-cell rows are section headers."""
    parser = _IsinTableParser()
    parser.feed(html)
    out: list[tuple[str, list[str]]] = []
    section = ""
    for cells in parser.rows:
        if len(cells) == 1:
            section = cells[0].strip()
        elif len(cells) == 7 and section:
            out.append((section, cells))
    return out
