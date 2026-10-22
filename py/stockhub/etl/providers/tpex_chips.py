"""TPEx chip tables (籌碼), mixed into TpexProvider.

- insti/dailyTrade  shares per stock by institutional group. The new site serves 2014-12-01
                    on (earlier dates return an empty table); 16 columns until early 2018
                    (foreign dealers not split; the switch fell between 01-02 and 01-15),
                    24 since (foreign without and with foreign dealers, trust, dealers
                    own/hedge/total, grand total). The width decides, not the date.
- margin/balance    margin and short balances per stock, in lots, with a totals row
- insti/qfii        foreign and mainland holdings per stock
- insti/summary     market-wide traded value per institutional group; before 2019 the
                    table lacks foreign investors and its labels are mis-encoded, so unused
"""

from __future__ import annotations

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
    TransientProviderError,
)
from stockhub.etl.providers.http import get_json_bytes
from stockhub.etl.providers.twse_chips import (
    LOT,
    THOUSAND,
    loads,
    percent,
    to_int,
    with_dealer_total,
)

INSTI_URL = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
MARGIN_URL = "https://www.tpex.org.tw/www/zh-tw/margin/balance"
QFII_URL = "https://www.tpex.org.tw/www/zh-tw/insti/qfii"
SUMMARY_URL = "https://www.tpex.org.tw/www/zh-tw/insti/summary"

SUMMARY_INVESTORS: dict[str, Investor | None] = {
    "外資及陸資合計": None,  # foreign incl. foreign dealers; the parts are stored instead
    "外資及陸資(不含自營商)": "foreign",
    "外資及陸資(不含外資自營商)": "foreign",
    "外資及陸資": "foreign",
    "外資自營商": "foreign_dealer",
    "投信": "trust",
    "自營商合計": "dealer",
    "自營商": "dealer",
    "自營商(自行買賣)": "dealer_self",
    "自營商(避險)": "dealer_hedge",
    "三大法人合計": "total",
}


NO_DATA_STAT = "沒有符合條件的資料"


def tpex_tables(raw: RawResponse) -> list[dict[str, Any]] | None:
    """Non-empty tables of a response for the requested date; None when it has no rows."""
    data = loads(raw.payload)
    if str(data.get("stat", "")).lower() != "ok":
        raise ValueError(f"unexpected stat {data.get('stat')!r}")
    requested = date.fromisoformat(raw.params["date"])
    if data.get("date") != f"{requested:%Y%m%d}":
        raise ValueError(f"asked for {requested}, got data for {data.get('date')}")
    tables = [t for t in data.get("tables") or [] if t.get("data")]
    return tables or None


def _insti_row(day: date, row: list[Any]) -> InstitutionalTrade:
    v = [to_int(c) for c in row[2:]]
    symbol = str(row[0]).strip()
    if len(v) == 22:  # since early 2018
        return InstitutionalTrade(
            symbol=symbol,
            trade_date=day,
            foreign_buy=v[0],
            foreign_sell=v[1],
            foreign_net=v[2],
            foreign_dealer_buy=v[3],
            foreign_dealer_sell=v[4],
            foreign_dealer_net=v[5],
            trust_buy=v[9],
            trust_sell=v[10],
            trust_net=v[11],
            dealer_self_net=v[14],
            dealer_hedge_net=v[17],
            dealer_buy=v[18],
            dealer_sell=v[19],
            dealer_net=v[20],
            total_net=v[21],
        )
    if len(v) == 14:  # 2014-12-01 .. early 2018
        return InstitutionalTrade(
            symbol=symbol,
            trade_date=day,
            foreign_buy=v[0],
            foreign_sell=v[1],
            foreign_net=v[2],
            trust_buy=v[3],
            trust_sell=v[4],
            trust_net=v[5],
            dealer_net=v[6],
            dealer_buy=v[7] + v[10],
            dealer_sell=v[8] + v[11],
            dealer_self_net=v[9],
            dealer_hedge_net=v[12],
            total_net=v[13],
        )
    raise ValueError(f"unexpected institutional row width {len(row)}")


class TpexChipsMixin(
    InstitutionalTradeProvider,
    MarginProvider,
    ForeignHoldingProvider,
    MarketInstitutionalProvider,
):
    client: httpx.Client
    institutional_since: ClassVar[dict[Market, date]] = {"tpex": date(2014, 12, 1)}
    margin_since: ClassVar[dict[Market, date]] = {"tpex": date(2007, 1, 2)}
    foreign_holding_since: ClassVar[dict[Market, date]] = {"tpex": date(2012, 1, 2)}
    market_institutional_since: ClassVar[dict[Market, date]] = {"tpex": date(2019, 1, 2)}

    def _get_day(
        self, url: str, dataset: str, trade_date: date, market: Market, **params: str
    ) -> RawResponse:
        if market != "tpex":
            raise PermanentProviderError(f"tpex does not publish {market} {dataset}")
        query = {**params, "date": f"{trade_date:%Y/%m/%d}", "response": "json"}
        body = get_json_bytes(self.client, url, query)
        if b'"stat"' in body[:200] and NO_DATA_STAT.encode() in body[:200]:
            # TPEx answers a day without data with its date and empty tables; this bare
            # TWSE-style notice came back once mid-backfill for a day that has data (2017-07-10
            # qfii), so it is a hiccup to retry, not a holiday.
            raise TransientProviderError(f"tpex {dataset} {trade_date}: bare no-data notice")
        return RawResponse(dataset, body, {"date": trade_date.isoformat(), "market": market})

    # ------------------------------------------------------------------ institutional

    def fetch_institutional_trades(self, trade_date: date, market: Market) -> RawResponse:
        return self._get_day(INSTI_URL, "insti_daily", trade_date, market, type="Daily", sect="EW")

    def parse_institutional_trades(self, raw: RawResponse) -> list[InstitutionalTrade]:
        tables = tpex_tables(raw)
        if tables is None:
            return []
        day = date.fromisoformat(raw.params["date"])
        return [_insti_row(day, row) for table in tables for row in table["data"]]

    # ------------------------------------------------------------------ margin

    def fetch_margin(self, trade_date: date, market: Market) -> RawResponse:
        return self._get_day(MARGIN_URL, "margin_balance", trade_date, market)

    def parse_margin(self, raw: RawResponse) -> list[MarginTable]:
        tables = tpex_tables(raw)
        if tables is None:
            return []
        day = date.fromisoformat(raw.params["date"])
        table = tables[0]
        col = {str(f).strip(): i for i, f in enumerate(table["fields"])}

        def shares(row: list[Any], name: str) -> int:
            return to_int(row[col[name]]) * LOT

        rows = [
            MarginBalance(
                symbol=str(r[col["代號"]]).strip(),
                trade_date=day,
                margin_prev=shares(r, "前資餘額(張)"),
                margin_buy=shares(r, "資買"),
                margin_sell=shares(r, "資賣"),
                margin_redeem=shares(r, "現償"),
                margin_balance=shares(r, "資餘額"),
                margin_limit=shares(r, "資限額"),
                short_prev=shares(r, "前券餘額(張)"),
                short_sell=shares(r, "券賣"),
                short_cover=shares(r, "券買"),
                short_redeem=shares(r, "券償"),
                short_balance=shares(r, "券餘額"),
                short_limit=shares(r, "券限額"),
                offset_shares=shares(r, "資券相抵(張)"),
                note=str(r[col["備註"]]).strip() or None,
            )
            for r in table["data"]
        ]
        summary = {str(r[1]).strip(): r for r in table.get("summary") or [] if len(r) > 1}
        total = None
        if "合計(張)" in summary:
            lots, amount = summary["合計(張)"], summary.get("融資金(仟元)")
            total = MarketMargin(
                market="tpex",
                trade_date=day,
                margin_balance=shares(lots, "資餘額"),
                short_balance=shares(lots, "券餘額"),
                margin_balance_amount=Decimal(to_int(amount[col["資餘額"]])) * THOUSAND
                if amount is not None
                else None,
            )
        return [MarginTable(market="tpex", trade_date=day, rows=rows, total=total)]

    # ------------------------------------------------------------------ foreign holdings

    def fetch_foreign_holdings(self, trade_date: date, market: Market) -> RawResponse:
        return self._get_day(QFII_URL, "qfii", trade_date, market)

    def parse_foreign_holdings(self, raw: RawResponse) -> list[ForeignHolding]:
        tables = tpex_tables(raw)
        if tables is None:
            return []
        day = date.fromisoformat(raw.params["date"])
        table = tables[0]
        # Headers carry their formulas: 發行股數(A), 僑外資及陸資持有股數(C), ...(E=C/A).
        col = {str(f).split("(")[0].strip(): i for i, f in enumerate(table["fields"])}
        out = []
        for r in table["data"]:
            ratio = percent(r[col["僑外資及陸資持股比率"]])
            out.append(
                ForeignHolding(
                    symbol=str(r[col["代號"]]).strip(),
                    trade_date=day,
                    issued_shares=to_int(r[col["發行股數"]]),
                    foreign_shares=to_int(r[col["僑外資及陸資持有股數"]]),
                    foreign_ratio=ratio if ratio is not None else Decimal(0),
                    limit_ratio=percent(r[col["法令投資上限比率"]]),
                )
            )
        return out

    # ------------------------------------------------------------------ market totals

    def fetch_market_institutional(self, trade_date: date, market: Market) -> RawResponse:
        return self._get_day(SUMMARY_URL, "insti_summary", trade_date, market, type="Daily")

    def parse_market_institutional(self, raw: RawResponse) -> list[MarketInstitutional]:
        tables = tpex_tables(raw)
        if tables is None:
            return []
        day = date.fromisoformat(raw.params["date"])
        rows = []
        for cells in tables[0]["data"]:
            if not cells:  # trailing empty row
                continue
            name, buy, sell, net = cells
            label = str(name).replace("　", "").replace("*", "").strip()
            if label not in SUMMARY_INVESTORS:
                raise ValueError(f"unknown summary row {name!r}")
            investor = SUMMARY_INVESTORS[label]
            if investor is None:
                continue
            rows.append(
                MarketInstitutional(
                    market="tpex",
                    trade_date=day,
                    investor=investor,
                    buy_amount=Decimal(to_int(buy)),
                    sell_amount=Decimal(to_int(sell)),
                    net_amount=Decimal(to_int(net)),
                )
            )
        return with_dealer_total(rows)
