"""FRED, Federal Reserve Bank of St. Louis (official, public CSV without an API key).

graph/fredgraph.csv?id=&cosd=&coed= returns `observation_date,<ID>` rows; missing days are
blank or '.'. Primary for US rates and monthly macro data, fallback for the indices, oil and
USD/TWD that Yahoo serves (D-105). FRED dates are the source's own: US trading days for
markets, the first day of the month for monthly data. One request per second.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import ClassVar

import httpx

from stockhub.etl.providers.base import (
    MarketSeriesProvider,
    PermanentProviderError,
    RawResponse,
    SeriesObservation,
)
from stockhub.etl.providers.http import get_bytes, make_client
from stockhub.etl.providers.registry import register_provider

CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


@register_provider
class FredProvider(MarketSeriesProvider):
    name: ClassVar[str] = "fred"
    min_interval: ClassVar[float] = 1.0
    series_symbols: ClassVar[dict[str, str]] = {
        "SPX": "SP500",
        "NASDAQ": "NASDAQCOM",
        "N225": "NIKKEI225",
        "VIX": "VIXCLS",
        "WTI": "DCOILWTICO",
        "USDTWD": "DEXTAUS",
        "UST2Y": "DGS2",
        "UST10Y": "DGS10",
        "FED_UPPER": "DFEDTARU",
        "US_CPI": "CPIAUCSL",
        "US_UNRATE": "UNRATE",
    }

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or make_client()

    def fetch_market_series(self, code: str, start: date, end: date) -> RawResponse:
        symbol = self.series_symbols.get(code)
        if symbol is None:
            raise PermanentProviderError(f"fred does not serve series {code}")
        params = {"id": symbol, "cosd": start.isoformat(), "coed": end.isoformat()}
        body = get_bytes(self.client, CSV_URL, params)
        return RawResponse(
            "fredgraph",
            body,
            {"code": code, "symbol": symbol, "start": start.isoformat(), "end": end.isoformat()},
        )

    def parse_market_series(self, raw: RawResponse) -> list[SeriesObservation]:
        code, symbol = raw.params["code"], raw.params["symbol"]
        start, end = date.fromisoformat(raw.params["start"]), date.fromisoformat(raw.params["end"])
        payload = raw.payload
        text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else str(payload)
        rows = csv.reader(io.StringIO(text))
        header = [h.strip() for h in next(rows, [])]
        if len(header) != 2 or header[0] not in ("observation_date", "DATE") or header[1] != symbol:
            raise ValueError(f"unexpected FRED header {header}")
        out = []
        for cells in rows:
            if len(cells) != 2:
                continue
            day = date.fromisoformat(cells[0].strip())
            try:
                value = Decimal(cells[1].strip())
            except InvalidOperation:  # '' or '.' = no observation that day
                continue
            if start <= day <= end:
                out.append(SeriesObservation(code=code, obs_date=day, value=value))
        return out
