"""Offline stand-ins for TWSE/TPEx: httpx MockTransport serving the recorded fixtures."""

from __future__ import annotations

from pathlib import Path

import httpx

from stockhub.common.rawstore import RawStore
from stockhub.etl.providers.fred import FredProvider
from stockhub.etl.providers.http import make_client
from stockhub.etl.providers.mis import TwseMisProvider
from stockhub.etl.providers.ndc import NdcProvider
from stockhub.etl.providers.registry import ProviderRegistry
from stockhub.etl.providers.router import ProviderRouter, RateLimiter, RetryPolicy
from stockhub.etl.providers.tdcc import TdccProvider
from stockhub.etl.providers.tpex import TpexProvider
from stockhub.etl.providers.twse import TwseProvider
from stockhub.etl.providers.yahoo import YahooProvider

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
    elif path.endswith("/TWT48U_ALL"):
        name = "twse_twt48u_all.json"
    elif path.endswith("/tpex_exright_prepost"):
        name = "tpex_exright_prepost.json"
    elif path.endswith("/getStockInfo.jsp"):
        name = "twse_mis_20261016.json"
    elif path.endswith("/TWT49UDetail"):
        name = f"twse_twt49u_detail_{params['STK_NO']}_{params['T1']}.json"
        if not (FIXTURES / name).exists():
            return httpx.Response(200, json={"stat": "無相關資料"})
    elif path.rsplit("/", 1)[-1] in CHIP_FIXTURES:
        return chip_response(request)
    elif path.endswith("/getOD.ashx"):
        name = "tdcc_1_5.csv"
    elif path.endswith("/MI_5MINS_HIST") or path.endswith("/indexInfo/inx"):
        return index_response(request)
    elif "/v8/finance/chart/" in path or path.endswith("/fredgraph.csv"):
        return series_response(request)
    elif request.url.host == "data.gov.tw":
        name = "datagov_6099.json"
    elif request.url.host == "ws.ndc.gov.tw":
        name = "ndc_business_indicators.zip"
    elif path.rsplit("/", 1)[-1] in ACTION_FIXTURES:
        # Corporate action tables: recorded rows for 2025 (and 2004 for TWT49U) only.
        year = params["startDate"][:4]
        name = ACTION_FIXTURES[path.rsplit("/", 1)[-1]].get(year, "")
        if not name:
            if "tpex" in request.url.host:
                return httpx.Response(200, json={"stat": "ok", "tables": [{"fields": []}]})
            return httpx.Response(200, json={"stat": "很抱歉，沒有符合條件的資料!"})
    else:
        return httpx.Response(404)
    return httpx.Response(200, content=fixture(name))


ACTION_FIXTURES = {
    "TWT49U": {"2025": "twse_twt49u_2025.json", "2004": "twse_twt49u_2004.json"},
    "TWTAUU": {"2025": "twse_twtauu_2025.json"},
    "TWTB8U": {"2025": "twse_twtb8u_2025.json"},
    "TWTCAU": {"2025": "twse_twtcau_2025.json"},
    "exDailyQ": {"2025": "tpex_exdailyq_2025.json"},
    "revivt": {"2025": "tpex_revivt_2025.json"},
}


CHIP_FIXTURES: dict[str, dict[str, str]] = {
    "T86": {
        "20261016": "twse_t86_20261016.json",
        "20120502": "twse_t86_20120502.json",
        "20150601": "twse_t86_20150601.json",
    },
    "MI_MARGN": {"20261016": "twse_mi_margn_20261016.json"},
    "MI_QFIIS": {
        "20261016": "twse_mi_qfiis_20261016.json",
        "20120502": "twse_mi_qfiis_20120502.json",
    },
    "BFI82U": {"20261016": "twse_bfi82u_20261016.json", "20120502": "twse_bfi82u_20120502.json"},
    "dailyTrade": {"20261016": "tpex_insti_20261016.json", "20150601": "tpex_insti_20150601.json"},
    "balance": {"20261016": "tpex_margin_20261016.json"},
    "qfii": {"20261016": "tpex_qfii_20261016.json"},
    "summary": {"20261016": "tpex_summary_20261016.json"},
}
"""Chip tables by endpoint and date; any other date answers like a holiday."""


def chip_response(request: httpx.Request) -> httpx.Response:
    endpoint = request.url.path.rsplit("/", 1)[-1]
    params = request.url.params
    day = (params.get("date") or params.get("dayDate") or "").replace("/", "")
    name = CHIP_FIXTURES[endpoint].get(day)
    if name is not None:
        return httpx.Response(200, content=fixture(name))
    if "tpex" in request.url.host:
        # TPEx echoes the date with empty tables.
        return httpx.Response(200, json={"stat": "ok", "date": day, "tables": [{"data": []}]})
    return httpx.Response(200, json={"stat": "很抱歉，沒有符合條件的資料!", "total": 0})


def index_response(request: httpx.Request) -> httpx.Response:
    """TAIEX and TPEx index months: October 2026 only; other months answer empty."""
    date_ = request.url.params["date"]
    if request.url.path.endswith("/MI_5MINS_HIST"):
        if date_ == "20261001":
            return httpx.Response(200, content=fixture("twse_mi_5mins_hist_202610.json"))
        return httpx.Response(200, json={"stat": "很抱歉，沒有符合條件的資料!"})
    if date_ == "2026/10/01":
        return httpx.Response(200, content=fixture("tpex_inx_202610.json"))
    fields = ["日期", "開市", "最高", "最低", "收市", "漲/跌"]
    return httpx.Response(200, json={"stat": "ok", "tables": [{"fields": fields, "data": []}]})


def series_response(request: httpx.Request) -> httpx.Response:
    """Yahoo serves ^GSPC (2026-10-01..10-20) and nothing else; FRED serves DGS10 and an
    empty CSV for any other id."""
    if "/v8/finance/chart/" in request.url.path:
        if request.url.path.endswith("/%5EGSPC") or request.url.path.endswith("/^GSPC"):
            return httpx.Response(200, content=fixture("yahoo_chart_gspc.json"))
        error = {"code": "Not Found", "description": "No data found, symbol may be delisted"}
        return httpx.Response(404, json={"chart": {"result": None, "error": error}})
    series = request.url.params["id"]
    if series == "DGS10":
        return httpx.Response(200, content=fixture("fred_dgs10.csv"))
    return httpx.Response(200, content=f"observation_date,{series}\n".encode())


def official_router(rawstore: RawStore, handler=official_handler) -> ProviderRouter:  # type: ignore[no-untyped-def]
    client = make_client(httpx.MockTransport(handler))
    twse, tpex = TwseProvider(client), TpexProvider(client)
    registry = ProviderRegistry(
        {
            "price": [twse, tpex],
            "calendar": [twse],
            "securities": [twse],
            "delistings": [twse, tpex],
            "corporate_actions": [twse, tpex],
            "dividend_details": [twse],
            "ex_rights_previews": [twse, tpex],
            "quote": [TwseMisProvider(client)],
            "institutional_trades": [twse, tpex],
            "margin": [twse, tpex],
            "foreign_holdings": [twse, tpex],
            "market_institutional": [twse, tpex],
            "shareholding_distribution": [TdccProvider(client)],
            "market_series": [twse, tpex, YahooProvider(client), FredProvider(client)],
            "macro_release": [NdcProvider(client)],
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
