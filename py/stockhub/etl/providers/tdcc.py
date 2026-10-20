"""Taiwan Depository & Clearing Corp. open data (official): weekly shareholding distribution.

getOD.ashx?id=1-5 (集保戶股權分散表) is a CSV of every security's 17 brackets for the latest
week only; there is no date parameter, so history accumulates from our first fetch. The
host has no robots.txt; we fetch it once a day.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal
from typing import ClassVar

import httpx

from stockhub.etl.providers.base import (
    DistributionLevel,
    RawResponse,
    ShareholdingDistributionProvider,
)
from stockhub.etl.providers.http import get_bytes, make_client
from stockhub.etl.providers.registry import register_provider

DISTRIBUTION_URL = "https://opendata.tdcc.com.tw/getOD.ashx"
HEADER = ["資料日期", "證券代號", "持股分級", "人數", "股數", "占集保庫存數比例%"]
HUNDRED = Decimal(100)


def in_scope(symbol: str) -> bool:
    """Common stocks (four digits) and ETFs (00…, but not 000…, which are bonds and
    beneficiary certificates); the job keeps only symbols in the stock master anyway."""
    if len(symbol) == 4 and symbol.isdigit():
        return True
    return symbol.startswith("00") and not symbol.startswith("000")


@register_provider
class TdccProvider(ShareholdingDistributionProvider):
    name: ClassVar[str] = "tdcc"
    min_interval: ClassVar[float] = 3.0

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or make_client()

    def fetch_shareholding_distribution(self) -> RawResponse:
        body = get_bytes(self.client, DISTRIBUTION_URL, {"id": "1-5"})
        return RawResponse("distribution", body, {})

    def parse_shareholding_distribution(self, raw: RawResponse) -> list[DistributionLevel]:
        payload = raw.payload
        text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else str(payload)
        rows = csv.reader(io.StringIO(text))
        header = [h.strip() for h in next(rows, [])]
        if header != HEADER:
            raise ValueError(f"unexpected TDCC header {header}")
        out = []
        for cells in rows:
            if not cells:
                continue
            day, symbol, level, holders, shares, ratio = (c.strip() for c in cells)
            if not in_scope(symbol):
                continue
            out.append(
                DistributionLevel(
                    symbol=symbol,
                    week_date=date(int(day[:4]), int(day[4:6]), int(day[6:])),
                    level=int(level),
                    holders=int(holders),
                    shares=int(shares),
                    ratio=Decimal(ratio) / HUNDRED,
                )
            )
        if not out:
            raise ValueError("no rows parsed from the TDCC distribution file")
        return out
