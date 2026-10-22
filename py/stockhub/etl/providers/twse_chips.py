"""TWSE chip tables (籌碼), mixed into TwseProvider.

- fund/T86              shares bought/sold per stock by the institutional groups (from
                        2012-05-02). Three layouts: until 2014-11 dealers are one group; from
                        2014-12-01 split into own account and hedging; from 2017-12-18 foreign
                        dealers are listed apart from other foreign investors.
- marginTrading/MI_MARGN margin and short balances per stock, in lots, plus market totals
- fund/MI_QFIIS         foreign and mainland holdings per stock
- fund/BFI82U           market-wide traded value per institutional group
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar

import httpx

from stockhub.etl.providers.base import (
    ForeignHolding,
    ForeignHoldingProvider,
    InstitutionalTrade,
    InstitutionalTradeProvider,
    Investor,
    MarginBalance,
    MarginProvider,
    MarginTable,
    Market,
    MarketInstitutional,
    MarketInstitutionalProvider,
    MarketMargin,
    PermanentProviderError,
    RawResponse,
)
from stockhub.etl.providers.http import clean_number, get_json_bytes

T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
MARGIN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
QFIIS_URL = "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS"
BFI82U_URL = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"

NO_DATA = "沒有符合條件的資料"
NOT_YET = "查詢日期大於可查詢最大日期"
"""MI_QFIIS before the day's table is out (seen at 18:13 on a trading day)."""
LOT = 1000
HUNDRED = Decimal(100)
THOUSAND = Decimal(1000)


def to_int(value: object) -> int:
    """'1,234' / 1234 / 1234.0 -> 1234; blanks and dashes -> 0."""
    if isinstance(value, int | float):
        return int(value)
    text = clean_number(str(value))
    return int(Decimal(text)) if text is not None else 0


def percent(value: object) -> Decimal | None:
    """'72.34' / 72.34 / '72.34%' -> Decimal('0.7234'); blanks -> None."""
    text = clean_number(str(value).replace("%", ""))
    return Decimal(text) / HUNDRED if text is not None else None


def loads(payload: bytes | str | Any) -> Any:
    return json.loads(payload) if isinstance(payload, bytes | str) else payload


def twse_table(raw: RawResponse) -> dict[str, Any] | None:
    """The response body when it holds data for the requested date; None when TWSE has
    nothing for it (holiday, or not published yet)."""
    data = loads(raw.payload)
    stat = str(data.get("stat", ""))
    if NO_DATA in stat or NOT_YET in stat:
        return None
    if stat.upper() != "OK":
        raise ValueError(f"unexpected stat {stat!r}")
    requested = date.fromisoformat(raw.params["date"])
    if data.get("date") != f"{requested:%Y%m%d}":
        raise ValueError(f"asked for {requested}, got data for {data.get('date')}")
    result: dict[str, Any] = data
    return result


def _t86_row(day: date, cells: dict[str, str]) -> InstitutionalTrade:
    def get(name: str) -> int:
        return to_int(cells[name])

    def maybe(name: str) -> int | None:
        return get(name) if name in cells else None

    if "外陸資買進股數(不含外資自營商)" in cells:
        foreign = ("外陸資買進股數(不含外資自營商)", "外陸資賣出股數(不含外資自營商)",
                   "外陸資買賣超股數(不含外資自營商)")  # fmt: skip
    else:
        foreign = ("外資買進股數", "外資賣出股數", "外資買賣超股數")
    split = "自營商買進股數(自行買賣)" in cells
    if split:
        dealer_buy = get("自營商買進股數(自行買賣)") + get("自營商買進股數(避險)")
        dealer_sell = get("自營商賣出股數(自行買賣)") + get("自營商賣出股數(避險)")
    else:
        dealer_buy, dealer_sell = get("自營商買進股數"), get("自營商賣出股數")
    return InstitutionalTrade(
        symbol=cells["證券代號"],
        trade_date=day,
        foreign_buy=get(foreign[0]),
        foreign_sell=get(foreign[1]),
        foreign_net=get(foreign[2]),
        foreign_dealer_buy=maybe("外資自營商買進股數"),
        foreign_dealer_sell=maybe("外資自營商賣出股數"),
        foreign_dealer_net=maybe("外資自營商買賣超股數"),
        trust_buy=get("投信買進股數"),
        trust_sell=get("投信賣出股數"),
        trust_net=get("投信買賣超股數"),
        dealer_buy=dealer_buy,
        dealer_sell=dealer_sell,
        dealer_net=get("自營商買賣超股數"),
        dealer_self_net=get("自營商買賣超股數(自行買賣)") if split else None,
        dealer_hedge_net=get("自營商買賣超股數(避險)") if split else None,
        total_net=get("三大法人買賣超股數"),
    )


MARGIN_FIELDS = [
    "代號", "名稱",
    "買進", "賣出", "現金償還", "前日餘額", "今日餘額", "次一營業日限額",
    "買進", "賣出", "現券償還", "前日餘額", "今日餘額", "次一營業日限額",
    "資券互抵", "註記",
]  # fmt: skip
"""MI_MARGN repeats its column names for 融資 and 融券, so rows are read by position."""

BFI82U_INVESTORS: dict[str, Investor] = {
    "自營商": "dealer",
    "自營商(自行買賣)": "dealer_self",
    "自營商(避險)": "dealer_hedge",
    "投信": "trust",
    "外資及陸資": "foreign",
    "外資及陸資(不含外資自營商)": "foreign",
    "外資自營商": "foreign_dealer",
    "合計": "total",
}


def with_dealer_total(rows: list[MarketInstitutional]) -> list[MarketInstitutional]:
    """Add the dealer group when a table lists only its two parts (since 2014-12)."""
    by = {r.investor: r for r in rows}
    if "dealer" in by or not {"dealer_self", "dealer_hedge"} <= by.keys():
        return rows
    own, hedge = by["dealer_self"], by["dealer_hedge"]
    return [
        *rows,
        MarketInstitutional(
            market=own.market,
            trade_date=own.trade_date,
            investor="dealer",
            buy_amount=own.buy_amount + hedge.buy_amount,
            sell_amount=own.sell_amount + hedge.sell_amount,
            net_amount=own.net_amount + hedge.net_amount,
        ),
    ]


class TwseChipsMixin(
    InstitutionalTradeProvider,
    MarginProvider,
    ForeignHoldingProvider,
    MarketInstitutionalProvider,
):
    client: httpx.Client
    institutional_since: ClassVar[dict[Market, date]] = {"twse": date(2012, 5, 2)}
    margin_since: ClassVar[dict[Market, date]] = {"twse": date(2004, 1, 1)}
    foreign_holding_since: ClassVar[dict[Market, date]] = {"twse": date(2005, 1, 3)}
    market_institutional_since: ClassVar[dict[Market, date]] = {"twse": date(2004, 4, 7)}

    def _get_day(
        self, url: str, dataset: str, trade_date: date, market: Market, **params: str
    ) -> RawResponse:
        if market != "twse":
            raise PermanentProviderError(f"twse does not publish {market} {dataset}")
        body = get_json_bytes(self.client, url, {**params, "response": "json"})
        return RawResponse(dataset, body, {"date": trade_date.isoformat(), "market": market})

    # ------------------------------------------------------------------ institutional

    def fetch_institutional_trades(self, trade_date: date, market: Market) -> RawResponse:
        return self._get_day(
            T86_URL, "t86", trade_date, market, date=f"{trade_date:%Y%m%d}", selectType="ALLBUT0999"
        )

    def parse_institutional_trades(self, raw: RawResponse) -> list[InstitutionalTrade]:
        data = twse_table(raw)
        if data is None:
            return []
        day = date.fromisoformat(raw.params["date"])
        fields = list(data["fields"])
        return [
            _t86_row(day, {name: str(cell).strip() for name, cell in zip(fields, row, strict=True)})
            for row in data.get("data") or []
        ]

    # ------------------------------------------------------------------ margin

    def fetch_margin(self, trade_date: date, market: Market) -> RawResponse:
        return self._get_day(
            MARGIN_URL,
            "mi_margn",
            trade_date,
            market,
            date=f"{trade_date:%Y%m%d}",
            selectType="ALL",
        )

    def parse_margin(self, raw: RawResponse) -> list[MarginTable]:
        data = twse_table(raw)
        if data is None:
            return []
        day = date.fromisoformat(raw.params["date"])
        tables = data.get("tables") or []
        detail = next((t for t in tables if (t.get("fields") or [])[:1] == ["代號"]), None)
        if detail is None:
            raise ValueError("margin detail table not found")
        if [f.strip() for f in detail["fields"]] != MARGIN_FIELDS:
            raise ValueError(f"unexpected margin columns {detail['fields']}")
        rows = []
        for r in detail.get("data") or []:
            v = [to_int(c) * LOT for c in r[2:15]]
            rows.append(
                MarginBalance(
                    symbol=str(r[0]).strip(),
                    trade_date=day,
                    margin_buy=v[0],
                    margin_sell=v[1],
                    margin_redeem=v[2],
                    margin_prev=v[3],
                    margin_balance=v[4],
                    margin_limit=v[5],
                    short_cover=v[6],
                    short_sell=v[7],
                    short_redeem=v[8],
                    short_prev=v[9],
                    short_balance=v[10],
                    short_limit=v[11],
                    offset_shares=v[12],
                    note=str(r[15]).strip() or None,
                )
            )
        return [
            MarginTable(market="twse", trade_date=day, rows=rows, total=_margin_total(day, tables))
        ]

    # ------------------------------------------------------------------ foreign holdings

    def fetch_foreign_holdings(self, trade_date: date, market: Market) -> RawResponse:
        return self._get_day(
            QFIIS_URL,
            "mi_qfiis",
            trade_date,
            market,
            date=f"{trade_date:%Y%m%d}",
            selectType="ALLBUT0999",
        )

    def parse_foreign_holdings(self, raw: RawResponse) -> list[ForeignHolding]:
        data = twse_table(raw)
        if data is None:
            return []
        day = date.fromisoformat(raw.params["date"])
        # Before 2012 the headers said 外資 instead of 外資及陸資.
        col = {str(f).replace("及陸資", ""): i for i, f in enumerate(data["fields"])}
        out = []
        for r in data.get("data") or []:
            ratio = percent(r[col["全體外資持股比率"]])
            out.append(
                ForeignHolding(
                    symbol=str(r[col["證券代號"]]).strip(),
                    trade_date=day,
                    issued_shares=to_int(r[col["發行股數"]]),
                    foreign_shares=to_int(r[col["全體外資持有股數"]]),
                    foreign_ratio=ratio if ratio is not None else Decimal(0),
                    limit_ratio=percent(r[col["外資共用法令投資上限比率"]])
                    if "外資共用法令投資上限比率" in col
                    else None,
                )
            )
        return out

    # ------------------------------------------------------------------ market totals

    def fetch_market_institutional(self, trade_date: date, market: Market) -> RawResponse:
        return self._get_day(
            BFI82U_URL, "bfi82u", trade_date, market, type="day", dayDate=f"{trade_date:%Y%m%d}"
        )

    def parse_market_institutional(self, raw: RawResponse) -> list[MarketInstitutional]:
        data = twse_table(raw)
        if data is None:
            return []
        day = date.fromisoformat(raw.params["date"])
        rows = []
        for name, buy, sell, net in data.get("data") or []:
            investor = BFI82U_INVESTORS.get(str(name).strip())
            if investor is None:
                raise ValueError(f"unknown BFI82U row {name!r}")
            rows.append(
                MarketInstitutional(
                    market="twse",
                    trade_date=day,
                    investor=investor,
                    buy_amount=Decimal(to_int(buy)),
                    sell_amount=Decimal(to_int(sell)),
                    net_amount=Decimal(to_int(net)),
                )
            )
        return with_dealer_total(rows)


def _margin_total(day: date, tables: list[dict[str, Any]]) -> MarketMargin | None:
    """Market balances from the 信用交易統計 table (lots, and the loan amount in thousands)."""
    summary = next((t for t in tables if (t.get("fields") or [])[:1] == ["項目"]), None)
    if summary is None:
        return None
    col = {f: i for i, f in enumerate(summary["fields"])}
    by = {str(r[0]).strip(): r for r in summary.get("data") or []}
    if "融資(交易單位)" not in by or "融券(交易單位)" not in by:
        return None
    amount = by.get("融資金額(仟元)")
    return MarketMargin(
        market="twse",
        trade_date=day,
        margin_balance=to_int(by["融資(交易單位)"][col["今日餘額"]]) * LOT,
        short_balance=to_int(by["融券(交易單位)"][col["今日餘額"]]) * LOT,
        margin_balance_amount=Decimal(to_int(amount[col["今日餘額"]])) * THOUSAND
        if amount is not None
        else None,
    )
