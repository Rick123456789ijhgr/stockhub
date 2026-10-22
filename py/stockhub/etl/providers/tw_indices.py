"""Taiwan market indices from the exchanges (official), one calendar month per request.

- TWSE TAIEX/MI_5MINS_HIST: 發行量加權股價指數 daily OHLC of one month (since 1999).
- TPEx indexInfo/inx: 櫃買指數 daily OHLC of one month (since 2004 at least; the newer
  indexInfo/inxh and the OpenAPI tpex_index only serve recent months).
Both mixins rely on the host class for `client` and its 3-second rate limit.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar

import httpx

from stockhub.etl.providers.base import (
    MarketSeriesProvider,
    PermanentProviderError,
    RawResponse,
    SeriesObservation,
)
from stockhub.etl.providers.http import clean_number, get_json_bytes, roc_date

TAIEX_URL = "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST"
TPEX_INDEX_URL = "https://www.tpex.org.tw/www/zh-tw/indexInfo/inx"
TWSE_NO_DATA = "沒有符合條件的資料"


def _loads(payload: Any) -> Any:
    return json.loads(payload) if isinstance(payload, bytes | str) else payload


def _number(value: str) -> Decimal:
    text = clean_number(value)
    if text is None:
        raise ValueError(f"missing index value {value!r}")
    return Decimal(text)


def _check_month(code: str, start: date, end: date) -> None:
    if (start.year, start.month) != (end.year, end.month):
        raise PermanentProviderError(f"{code}: one calendar month per request ({start}..{end})")


def _ohlc_rows(code: str, rows: list[list[str]], start: date, end: date) -> list[SeriesObservation]:
    out = []
    for row in rows:
        day = roc_date(row[0])
        if start <= day <= end:
            out.append(
                SeriesObservation(
                    code=code,
                    obs_date=day,
                    open=_number(row[1]),
                    high=_number(row[2]),
                    low=_number(row[3]),
                    value=_number(row[4]),
                )
            )
    return out


def _range(raw: RawResponse) -> tuple[str, date, date]:
    return (
        raw.params["code"],
        date.fromisoformat(raw.params["start"]),
        date.fromisoformat(raw.params["end"]),
    )


class TwseIndexMixin(MarketSeriesProvider):
    client: httpx.Client
    series_symbols: ClassVar[dict[str, str]] = {"TAIEX": "MI_5MINS_HIST"}
    series_monthly: ClassVar[bool] = True

    def fetch_market_series(self, code: str, start: date, end: date) -> RawResponse:
        if code not in self.series_symbols:
            raise PermanentProviderError(f"twse does not serve series {code}")
        _check_month(code, start, end)
        params = {"date": f"{start:%Y%m}01", "response": "json"}
        body = get_json_bytes(self.client, TAIEX_URL, params)
        return RawResponse(
            "taiex_hist", body, {"code": code, "start": start.isoformat(), "end": end.isoformat()}
        )

    def parse_market_series(self, raw: RawResponse) -> list[SeriesObservation]:
        code, start, end = _range(raw)
        data = _loads(raw.payload)
        stat = str(data.get("stat", ""))
        if TWSE_NO_DATA in stat:
            return []
        if stat.upper() != "OK":
            raise ValueError(f"unexpected stat {stat!r}")
        fields = [f.strip() for f in data.get("fields", [])]
        if fields[:5] != ["日期", "開盤指數", "最高指數", "最低指數", "收盤指數"]:
            raise ValueError(f"unexpected MI_5MINS_HIST fields {fields}")
        return _ohlc_rows(code, data.get("data") or [], start, end)


class TpexIndexMixin(MarketSeriesProvider):
    client: httpx.Client
    series_symbols: ClassVar[dict[str, str]] = {"TPEX": "inx"}
    series_monthly: ClassVar[bool] = True

    def fetch_market_series(self, code: str, start: date, end: date) -> RawResponse:
        if code not in self.series_symbols:
            raise PermanentProviderError(f"tpex does not serve series {code}")
        _check_month(code, start, end)
        params = {"date": f"{start:%Y/%m}/01", "response": "json"}
        body = get_json_bytes(self.client, TPEX_INDEX_URL, params)
        return RawResponse(
            "index_inx", body, {"code": code, "start": start.isoformat(), "end": end.isoformat()}
        )

    def parse_market_series(self, raw: RawResponse) -> list[SeriesObservation]:
        code, start, end = _range(raw)
        data = _loads(raw.payload)
        if str(data.get("stat", "")).lower() != "ok":
            raise ValueError(f"unexpected stat {data.get('stat')!r}")
        tables = data.get("tables") or []
        if not tables:
            raise ValueError("table not found")
        fields = [f.strip() for f in tables[0].get("fields", [])]
        if fields[:5] != ["日期", "開市", "最高", "最低", "收市"]:
            raise ValueError(f"unexpected indexInfo/inx fields {fields}")
        return _ohlc_rows(code, tables[0].get("data") or [], start, end)
