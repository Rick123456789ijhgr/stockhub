"""TWSE MIS (mis.twse.com.tw): intraday snapshots for listed and OTC securities.

getStockInfo.jsp is the exchange's own real-time page feed, the same endpoint the twstock
package wraps; calling it directly keeps one HTTP stack and no extra dependency. It is not
a documented API: fields can change, and the page itself asks clients to wait 5 s between
requests (userDelay), so polling stays at 30 s for a short list of symbols.

Fields used: c symbol, ex tse/otc, d trade date, t last trade time, z last trade ('-' when
none this tick), o/h/l, y previous close (reference), v cumulative volume in lots,
b/a best five bids/asks joined by '_'.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

import httpx

from stockhub.common.timeutil import TAIPEI
from stockhub.etl.providers.base import Market, Quote, QuoteProvider, RawResponse
from stockhub.etl.providers.http import get_json_bytes, make_client
from stockhub.etl.providers.registry import register_provider

MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
CHANNEL: dict[Market, str] = {"twse": "tse", "tpex": "otc"}
MARKET_OF: dict[str, Market] = {v: k for k, v in CHANNEL.items()}


def _price(value: Any) -> Decimal | None:
    """'2420.0000' -> Decimal; '-', '', '0' -> None (no price this tick)."""
    if not isinstance(value, str):
        return None
    try:
        number = Decimal(value.strip())
    except InvalidOperation:
        return None
    return number if number > 0 else None


def _best(levels: Any) -> Decimal | None:
    """First of the '_'-joined order book levels."""
    if not isinstance(levels, str):
        return None
    return _price(levels.split("_", 1)[0])


def _snapshot_time(trade_date: date, item: dict[str, Any]) -> datetime:
    """Time of the last trade ('t', Taipei); 'tlong' is when the page refreshed instead."""
    try:
        clock = time.fromisoformat(str(item.get("t")))
    except ValueError:
        return datetime.fromtimestamp(int(item["tlong"]) / 1000, tz=UTC)
    return datetime.combine(trade_date, clock, tzinfo=TAIPEI).astimezone(UTC)


@register_provider
class TwseMisProvider(QuoteProvider):
    name: ClassVar[str] = "twse_mis"
    min_interval: ClassVar[float] = 5.0
    max_symbols: ClassVar[int] = 50

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or make_client()

    def fetch_quotes(self, symbols: Sequence[tuple[str, Market]]) -> RawResponse:
        if len(symbols) > self.max_symbols:
            raise ValueError(f"at most {self.max_symbols} symbols per request")
        channels = "|".join(f"{CHANNEL[market]}_{symbol}.tw" for symbol, market in symbols)
        params = {"ex_ch": channels, "json": "1", "delay": "0"}
        body = get_json_bytes(self.client, MIS_URL, params)
        return RawResponse("stock_info", body, {"symbols": [s for s, _ in symbols]})

    def parse_quotes(self, raw: RawResponse) -> list[Quote]:
        payload = raw.payload
        data = json.loads(payload) if isinstance(payload, bytes | str) else payload
        if data.get("rtcode") != "0000":
            raise ValueError(f"unexpected rtcode {data.get('rtcode')!r}: {data.get('rtmessage')}")
        quotes = []
        for item in data.get("msgArray") or []:
            market = MARKET_OF.get(str(item.get("ex")))
            if market is None or not item.get("tlong") or not item.get("d"):
                continue
            lots = str(item.get("v") or "0").strip()
            day = str(item["d"])
            trade_date = date(int(day[:4]), int(day[4:6]), int(day[6:8]))
            quotes.append(
                Quote(
                    symbol=str(item["c"]).strip(),
                    market=market,
                    trade_date=trade_date,
                    at=_snapshot_time(trade_date, item),
                    price=_price(item.get("z")),
                    open=_price(item.get("o")),
                    high=_price(item.get("h")),
                    low=_price(item.get("l")),
                    prev_close=_price(item.get("y")),
                    volume=int(lots) * 1000 if lots.isdigit() else 0,
                    bid=_best(item.get("b")),
                    ask=_best(item.get("a")),
                )
            )
        return quotes
