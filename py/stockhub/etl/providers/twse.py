"""Taiwan Stock Exchange (official): daily quotes, holiday schedule, ISIN master lists.

Endpoints (robots.txt allows them; we stay at one request per 3 s):
- MI_INDEX?type=ALLBUT0999  every listed security's daily quote for one date (since 2004)
- holidaySchedule           announced holidays of a year (published from 2021)
- isin.twse.com.tw          master list with listing dates, for TWSE (strMode=2) and TPEx (4)
- company/suspendListing    companies delisted in a year (終止上市公司, from 2001)
- TWT49U / TWTAUU / TWTB8U / TWTCAU  ex-rights/dividend results, capital reductions (from
  2011), par-value changes and ETF splits, each with the exchange's reference price
- OpenAPI opendata/t187ap0x  latest financial statements, monthly revenue and company
  profiles of listed companies (see mops_openapi)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any, ClassVar

import httpx

from stockhub.etl.providers.base import (
    ActionDataset,
    ActionType,
    CalendarEntry,
    CalendarProvider,
    CorporateAction,
    CorporateActionProvider,
    DailyBar,
    Delisting,
    DelistingProvider,
    DividendDetail,
    DividendDetailProvider,
    ExRightsPreview,
    ExRightsPreviewProvider,
    Market,
    PermanentProviderError,
    PriceProvider,
    RawResponse,
    Security,
    SecurityListProvider,
)
from stockhub.etl.providers.http import (
    clean_number,
    get_bytes,
    get_json_bytes,
    make_client,
    preview_fields,
    roc_date,
)
from stockhub.etl.providers.mops_openapi import MopsOpenApiMixin
from stockhub.etl.providers.registry import register_provider

MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
HOLIDAY_URL = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule"
ISIN_URL = "https://isin.twse.com.tw/isin/C_public.jsp"
ISIN_MODES: dict[Market, int] = {"twse": 2, "tpex": 4}
DELISTED_URL = "https://www.twse.com.tw/rwd/zh/company/suspendListing"
PREVIEW_URL = "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"
OPENDATA = "https://openapi.twse.com.tw/v1/opendata"

NO_DATA = "沒有符合條件的資料"
# ISIN sections we keep; warrants, ETNs, TDRs, preferred shares and REITs are out of scope.
ISIN_SECTIONS = {"股票": "stock", "創新板": "stock", "ETF": "etf"}


def _loads(payload: bytes | str | Any) -> Any:
    return json.loads(payload) if isinstance(payload, bytes | str) else payload


def _decimal(value: str | None) -> Decimal | None:
    text = clean_number(value)
    return Decimal(text) if text is not None else None


def is_common_symbol(symbol: str) -> bool:
    """Four-digit codes are common stocks; letters mark preferred shares and 91xx are TDRs."""
    return len(symbol) == 4 and symbol.isdigit() and not symbol.startswith("91")


@register_provider
class TwseProvider(
    PriceProvider,
    CalendarProvider,
    SecurityListProvider,
    DelistingProvider,
    CorporateActionProvider,
    DividendDetailProvider,
    ExRightsPreviewProvider,
    MopsOpenApiMixin,
):
    name: ClassVar[str] = "twse"
    min_interval: ClassVar[float] = 3.0
    markets: ClassVar[frozenset[Market]] = frozenset({"twse"})
    security_markets: ClassVar[frozenset[Market]] = frozenset({"twse", "tpex"})
    delisting_markets: ClassVar[frozenset[Market]] = frozenset({"twse"})
    detail_markets: ClassVar[frozenset[Market]] = frozenset({"twse"})
    preview_markets: ClassVar[frozenset[Market]] = frozenset({"twse"})
    snapshot_markets: ClassVar[frozenset[Market]] = frozenset({"twse"})
    revenue_markets: ClassVar[frozenset[Market]] = frozenset({"twse"})
    profile_markets: ClassVar[frozenset[Market]] = frozenset({"twse"})
    mops_market: ClassVar[Market] = "twse"
    mops_urls: ClassVar[dict[str, str]] = {
        "IS": f"{OPENDATA}/t187ap06_L_ci",
        "BS": f"{OPENDATA}/t187ap07_L_ci",
        "revenue": f"{OPENDATA}/t187ap05_L",
        "profiles": f"{OPENDATA}/t187ap03_L",
    }
    detail_since: ClassVar[date] = date(2009, 1, 1)
    """TWT49UDetail answers 無相關資料 for earlier events; their TWT49U rows split 權值/息值."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or make_client()

    # ------------------------------------------------------------------ ex-rights previews

    def fetch_ex_rights_previews(self, market: Market) -> RawResponse:
        if market != "twse":
            raise PermanentProviderError(f"twse does not publish {market} previews")
        body = get_json_bytes(self.client, PREVIEW_URL)
        return RawResponse("twt48u_all", body, {"market": market})

    def parse_ex_rights_previews(self, raw: RawResponse) -> list[ExRightsPreview]:
        rows = _loads(raw.payload)
        if not isinstance(rows, list):
            raise ValueError("TWT48U_ALL: expected a JSON array")
        return [
            ExRightsPreview(
                symbol=r["Code"].strip(),
                market="twse",
                ex_date=roc_date(r["Date"]),
                **preview_fields(
                    r["Exdividend"],
                    r["CashDividend"],
                    r["StockDividendRatio"],
                    r["SubscriptionRatio"],
                    r["SubscriptionPricePerShare"],
                ),
            )
            for r in rows
        ]

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
                    name=row[col["證券名稱"]].strip() or None,
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
        for day_text, name, *rest in data.get("data", []):
            label = name.strip()
            description = str(rest[0]) if rest else ""
            # "...開始交易日" / "...最後交易日" are announced trading days; everything else
            # (holidays, "市場無交易，僅辦理結算交割作業") means the market is closed. The
            # description wins: 2021 listed 02-08 and 02-09 under "農曆春節前最後交易日"
            # while describing them as "市場無交易，僅辦理結算交割作業".
            trading = ("開始交易" in label or "最後交易" in label) and "無交易" not in description
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

    # ------------------------------------------------------------------ delistings

    def fetch_delistings(self, market: Market, year: int) -> RawResponse:
        if market != "twse":
            raise PermanentProviderError(f"twse does not publish {market} delistings")
        params = {"date": f"{year}0101", "response": "json"}
        body = get_json_bytes(self.client, DELISTED_URL, params)
        return RawResponse("suspend_listing", body, {"year": year, "market": market})

    def parse_delistings(self, raw: RawResponse) -> list[Delisting]:
        data = _loads(raw.payload)
        if str(data.get("status", "")).lower() != "ok":
            raise ValueError(f"unexpected status {data.get('status')!r}")
        col = {name: i for i, name in enumerate(data["fields"])}
        year = int(raw.params["year"])
        out = []
        for row in data.get("data") or []:
            symbol = row[col["上市編號"]].strip()
            day = roc_date(row[col["終止上市日期"]])
            if day.year == year and is_common_symbol(symbol):
                out.append(
                    Delisting(
                        symbol=symbol,
                        name=row[col["公司名稱"]].strip(),
                        market="twse",
                        delisted_date=day,
                    )
                )
        return out

    # ------------------------------------------------------------------ corporate actions

    action_sources: ClassVar[dict[tuple[Market, ActionDataset], date]] = {
        ("twse", "dividend"): date(2004, 1, 1),
        ("twse", "capital_reduction"): date(2011, 1, 1),  # TWTAUU refuses earlier dates
        ("twse", "par_value_change"): date(2004, 1, 1),
        ("twse", "etf_split"): date(2004, 1, 1),
    }

    def fetch_corporate_actions(
        self, market: Market, dataset: ActionDataset, start: date, end: date
    ) -> RawResponse:
        if (market, dataset) not in self.action_sources:
            raise PermanentProviderError(f"twse does not publish {market} {dataset}")
        params = {"startDate": f"{start:%Y%m%d}", "endDate": f"{end:%Y%m%d}", "response": "json"}
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

    # ------------------------------------------------------------------ dividend details

    def fetch_dividend_detail(self, market: Market, symbol: str, ex_date: date) -> RawResponse:
        if market != "twse":
            raise PermanentProviderError(f"twse has no dividend details for {market}")
        params = {"STK_NO": symbol, "T1": f"{ex_date:%Y%m%d}", "response": "json"}
        body = get_json_bytes(self.client, DETAIL_URL, params)
        return RawResponse(
            "dividend_detail",
            body,
            {"market": market, "symbol": symbol, "ex_date": ex_date.isoformat()},
        )

    def parse_dividend_detail(self, raw: RawResponse) -> list[DividendDetail]:
        data = _loads(raw.payload)
        stat = str(data.get("stat", ""))
        if NO_DATA in stat or "無相關資料" in stat:
            return []
        if stat.upper() != "OK":
            raise ValueError(f"unexpected stat {stat!r}")
        symbol, ex_date = raw.params["symbol"], date.fromisoformat(raw.params["ex_date"])
        fields = [_text(f) for f in data["fields"]]
        rows = [dict(zip(fields, map(_text, row), strict=True)) for row in data.get("data", [])]
        rows = [r for r in rows if r.get("股票代號") == symbol]
        return [parse_detail_row(symbol, ex_date, rows[0])] if rows else []

    def parse_corporate_actions(self, raw: RawResponse) -> list[CorporateAction]:
        data = _loads(raw.payload)
        stat = str(data.get("stat", ""))
        if NO_DATA in stat:
            return []
        if stat.upper() != "OK":
            raise ValueError(f"unexpected stat {stat!r}")
        col = {name: i for i, name in enumerate(data["fields"])}
        parse_row = _ACTION_ROW_PARSERS[raw.params["dataset"]]
        out = []
        for row in data.get("data") or []:
            cells = {name: _text(row[i]) for name, i in col.items()}
            action = parse_row(cells)
            if action is not None:
                out.append(action)
        return out


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


DETAIL_URL = "https://www.twse.com.tw/rwd/zh/exRight/TWT49UDetail"
DETAIL_FIELDS = {
    "cash": "(每股配發現金股利)除息",
    "free_shares": "A. 按普通股股東持股比例每千股無償配股",
    "offering": "C. (有償) 現金增資",
    "holders_part": "c. 原股東認購",
    "holders_per_mille": "按股東持股比例每千股認購",
    "price": "每股認購金額",
}


def _unit_number(value: object) -> Decimal | None:
    """'0.4 元／股', '140 股', '60,000,000 股', '' -> Decimal or None."""
    text = _text(value).replace("元／股", "").replace("元/股", "").replace("股", "")
    return _decimal(text)


def parse_detail_row(symbol: str, ex_date: date, cells: dict[str, str]) -> DividendDetail:
    """One TWT49UDetail row; per-holder share counts there are per 1000 existing shares.

    rights_ratio is the whole cash offering per existing share, as the exchange's reference
    price counts it: holders subscribe only part (c. 原股東認購; the rest is underwritten or
    for employees), so their per-1000 figure is scaled by C / c. Without an offering
    (C = 0) the per-1000 figure repeats the free allotment and is not a subscription.
    """

    def number(key: str) -> Decimal:
        return _unit_number(cells.get(DETAIL_FIELDS[key], "")) or Decimal(0)

    per_mille = Decimal(1000)
    offering, holders_part = number("offering"), number("holders_part")
    rights = Decimal(0)
    if offering > 0 and holders_part > 0:
        rights = number("holders_per_mille") / per_mille * offering / holders_part
    price = number("price")
    return DividendDetail(
        symbol=symbol,
        ex_date=ex_date,
        cash_dividend=number("cash"),
        stock_dividend_ratio=number("free_shares") / per_mille,
        rights_ratio=rights.quantize(Decimal("1E-8")),
        subscription_price=price if rights > 0 and price > 0 else None,
    )


ACTION_URLS: dict[str, str] = {
    "dividend": "https://www.twse.com.tw/rwd/zh/exRight/TWT49U",
    "capital_reduction": "https://www.twse.com.tw/rwd/zh/reducation/TWTAUU",
    "par_value_change": "https://www.twse.com.tw/rwd/zh/change/TWTB8U",
    "etf_split": "https://www.twse.com.tw/rwd/zh/split/TWTCAU",
}
DIVIDEND_TYPES: dict[str, ActionType] = {
    "息": "cash_dividend",
    "權": "stock_dividend",
    "權息": "cash_and_stock_dividend",
}


def _text(value: object) -> str:
    """Cells are strings, but older years serve some numbers as JSON floats."""
    return value.strip() if isinstance(value, str) else str(value)


def _dividend_row(cells: dict[str, str]) -> CorporateAction | None:
    symbol = cells["股票代號"]
    kind = DIVIDEND_TYPES.get(cells["權/息"])
    if kind is None or not _in_scope(symbol):
        return None
    if "息值" in cells:  # before ~2010 the table split 權值 and 息值
        cash = _decimal(cells["息值"])
    else:  # only the total is published; it is pure cash for 息
        cash = _decimal(cells["權值+息值"]) if kind == "cash_dividend" else None
    return CorporateAction(
        symbol=symbol,
        market="twse",
        ex_date=roc_date(cells["資料日期"]),
        action_type=kind,
        prev_close=_decimal(cells["除權息前收盤價"]),
        reference_price=_decimal(cells["除權息參考價"]),
        cash_dividend=cash if kind != "stock_dividend" else None,
    )


def _resumption_row(
    cells: dict[str, str], symbol_col: str, kind: ActionType | None
) -> CorporateAction | None:
    symbol = cells[symbol_col]
    if not _in_scope(symbol):
        return None
    prev = _decimal(cells["停止買賣前收盤價格"])
    ref = _decimal(cells["恢復買賣參考價"])
    if kind is None:  # par-value change: direction follows the price
        kind = "split" if prev is not None and ref is not None and ref < prev else "reverse_split"
    return CorporateAction(
        symbol=symbol,
        market="twse",
        ex_date=roc_date(cells["恢復買賣日期"]),
        action_type=kind,
        prev_close=prev,
        reference_price=ref,
    )


def _in_scope(symbol: str) -> bool:
    """Common stocks and ETFs (00xx…); warrants, TDRs and preferred shares are not stored."""
    return is_common_symbol(symbol) or symbol.startswith("00")


_ACTION_ROW_PARSERS: dict[str, Callable[[dict[str, str]], CorporateAction | None]] = {
    "dividend": _dividend_row,
    "capital_reduction": lambda c: _resumption_row(c, "股票代號", "capital_reduction"),
    "par_value_change": lambda c: _resumption_row(c, "股票代號", None),
    "etf_split": lambda c: _resumption_row(
        c, "ETF代號", "reverse_split" if c["分割(反分割)"] == "反分割" else "split"
    ),
}
