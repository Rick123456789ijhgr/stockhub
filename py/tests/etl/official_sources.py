"""Offline stand-ins for TWSE/TPEx: httpx MockTransport serving the recorded fixtures."""

from __future__ import annotations

from pathlib import Path

import httpx

from stockhub.common.rawstore import RawStore
from stockhub.etl.providers.http import make_client
from stockhub.etl.providers.registry import ProviderRegistry
from stockhub.etl.providers.router import ProviderRouter, RateLimiter, RetryPolicy
from stockhub.etl.providers.tpex import TpexProvider
from stockhub.etl.providers.twse import TwseProvider

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


FIELDS_TWSE = ["終止上市日期", "公司名稱", "上市編號"]
FIELDS_TPEX = ["股票代號", "公司名稱", "終止上櫃日期", "終止上櫃原因", "公司資料網址"]


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def official_handler(request: httpx.Request) -> httpx.Response:
    """Data exists for 2026-10-16 only; the 2026 holiday schedule is published."""
    path, params = request.url.path, request.url.params
    if path.endswith("/MI_INDEX"):
        name = (
            "twse_mi_index_20261016.json"
            if params["date"] == "20261016"
            else "twse_mi_index_nodata.json"
        )
    elif path.endswith("/afterTrading/otc"):
        name = (
            "tpex_otc_20261016.json" if params["date"] == "2026/10/16" else "tpex_otc_nodata.json"
        )
        if params["date"] != "2026/10/16":
            # The real API echoes the requested date in an otherwise empty table.
            body = fixture(name).replace(
                b'"20261017"', f'"{params["date"].replace("/", "")}"'.encode()
            )
            return httpx.Response(200, content=body)
    elif path.endswith("/holidaySchedule"):
        name = (
            "twse_holidays_2026.json"
            if params["date"] == "20260101"
            else "twse_holidays_empty.json"
        )
    elif path.endswith("/C_public.jsp"):
        name = "isin_twse.html" if params["strMode"] == "2" else "isin_tpex.html"
    elif path.endswith("/suspendListing"):
        if params["date"] != "20260101":
            return httpx.Response(200, json={"status": "ok", "fields": FIELDS_TWSE, "data": []})
        name = "twse_delisted_2026.json"
    elif path.endswith("/deListed"):
        if params["date"] != "2026":
            empty = {"stat": "ok", "tables": [{"fields": FIELDS_TPEX, "data": []}]}
            return httpx.Response(200, json=empty)
        name = "tpex_delisted_2026.json"
    else:
        return httpx.Response(404)
    return httpx.Response(200, content=fixture(name))


def official_router(rawstore: RawStore, handler=official_handler) -> ProviderRouter:  # type: ignore[no-untyped-def]
    client = make_client(httpx.MockTransport(handler))
    twse, tpex = TwseProvider(client), TpexProvider(client)
    registry = ProviderRegistry(
        {
            "price": [twse, tpex],
            "calendar": [twse],
            "securities": [twse],
            "delistings": [twse, tpex],
        }
    )
    no_wait = RateLimiter(clock=lambda: 0.0, sleep=lambda _: None)
    return ProviderRouter(
        registry,
        rawstore,
        retry=RetryPolicy(max_attempts=2, base_delay=0, jitter=0),
        limiter=no_wait,
        sleep=lambda _: None,
    )
