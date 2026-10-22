"""Yahoo Finance chart API (unofficial): daily history of international indices, FX and
futures. Primary source for the series FRED lacks (費半, KOSPI, gold, DXY) and for fresh
closes of the rest; FRED is the fallback (D-105).

v8/finance/chart/{symbol}?period1=&period2=&interval=1d answers JSON with epoch timestamps
of each session's open and the exchange's time zone, so bars are dated in the exchange's
local calendar (rule 2). An unknown symbol or a range before the symbol's history is a 4xx,
which the router treats as permanent and falls back. We keep one request per 2 s; this is
not an official API and may change, which is why every series has a fallback or an alert.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import httpx

from stockhub.common.timeutil import utcnow
from stockhub.etl.providers.base import (
    MarketSeriesProvider,
    PermanentProviderError,
    RawResponse,
    SeriesObservation,
)
from stockhub.etl.providers.http import get_json_bytes, make_client
from stockhub.etl.providers.registry import register_provider

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
DECIMALS = Decimal("0.0001")
"""Yahoo serves binary floats (7651.5400390625); four places keep every published digit."""


def _decimal(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value)).quantize(DECIMALS)


@register_provider
class YahooProvider(MarketSeriesProvider):
    name: ClassVar[str] = "yahoo"
    min_interval: ClassVar[float] = 2.0
    series_symbols: ClassVar[dict[str, str]] = {
        "TAIEX": "^TWII",
        "SPX": "^GSPC",
        "NASDAQ": "^IXIC",
        "SOX": "^SOX",
        "N225": "^N225",
        "KOSPI": "^KS11",
        "VIX": "^VIX",
        "GOLD": "GC=F",
        "WTI": "CL=F",
        "DXY": "DX-Y.NYB",
        "USDTWD": "TWD=X",
    }

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or make_client()

    def fetch_market_series(self, code: str, start: date, end: date) -> RawResponse:
        symbol = self.series_symbols.get(code)
        if symbol is None:
            raise PermanentProviderError(f"yahoo does not serve series {code}")
        # period2 is exclusive; a day past `end` (UTC) covers sessions east and west of UTC.
        params = {
            "period1": int(datetime.combine(start - timedelta(days=1), time(), UTC).timestamp()),
            "period2": int(datetime.combine(end + timedelta(days=2), time(), UTC).timestamp()),
            "interval": "1d",
        }
        body = get_json_bytes(self.client, CHART_URL + symbol, params)
        return RawResponse(
            "chart",
            body,
            {
                "code": code,
                "symbol": symbol,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "fetched_at": utcnow().isoformat(),
            },
        )

    def parse_market_series(self, raw: RawResponse) -> list[SeriesObservation]:
        code = raw.params["code"]
        start, end = date.fromisoformat(raw.params["start"]), date.fromisoformat(raw.params["end"])
        fetched_at = datetime.fromisoformat(raw.params["fetched_at"])
        payload = raw.payload
        data: Any = json.loads(payload) if isinstance(payload, bytes | str) else payload
        chart = data.get("chart") or {}
        if chart.get("error"):
            raise ValueError(f"yahoo error {chart['error']}")
        results = chart.get("result") or []
        if not results:
            raise ValueError("yahoo chart without result")
        result = results[0]
        meta = result.get("meta") or {}
        zone = ZoneInfo(meta.get("exchangeTimezoneName") or "UTC")
        stamps: list[int] = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        session = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
        out = []
        for i, stamp in enumerate(stamps):
            close = _decimal(quote.get("close", [])[i])
            if close is None:  # Yahoo prints null bars for some holidays
                continue
            # A bar of a session still open is a snapshot, not a close.
            if (
                session
                and session["start"] <= stamp < session["end"]
                and (fetched_at.timestamp() < session["end"])
            ):
                continue
            day = datetime.fromtimestamp(stamp, zone).date()
            if not start <= day <= end:
                continue
            out.append(
                SeriesObservation(
                    code=code,
                    obs_date=day,
                    open=_decimal(quote.get("open", [])[i]),
                    high=_decimal(quote.get("high", [])[i]),
                    low=_decimal(quote.get("low", [])[i]),
                    value=close,
                )
            )
        return out
