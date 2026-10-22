"""National Development Council (國發會, official): business indicators and the monitoring
light (景氣指標及燈號), government open data set 6099 on data.gov.tw.

The file is a ZIP of CSVs republished every month with the whole revised history; its
download URL changes with each release, so the fetch first reads the data set's metadata
from the data.gov.tw API and then downloads the ZIP it points to (two requests, once a day).
We keep the signal score with its light and the trend-adjusted leading and coincident
indices (不含趨勢指數), the ones NDC charts.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date
from decimal import Decimal
from typing import ClassVar

import httpx

from stockhub.etl.providers.base import MacroReleaseProvider, RawResponse, SeriesObservation
from stockhub.etl.providers.http import clean_number, get_bytes, get_json_bytes, make_client
from stockhub.etl.providers.registry import register_provider

DATASET_URL = "https://data.gov.tw/api/v2/rest/dataset/6099"
SIGNAL_COLUMN = "景氣對策信號綜合分數"
COLUMNS = {
    "TW_SIGNAL": SIGNAL_COLUMN,
    "TW_LEADING": "領先指標不含趨勢指數",
    "TW_COINCIDENT": "同時指標不含趨勢指數",
}
LIGHT_COLUMN = "景氣對策信號"
LIGHTS = {"紅", "黃紅", "綠", "黃藍", "藍"}


def download_url(metadata: bytes) -> str:
    """The ZIP distribution of the data set's current release."""
    result = json.loads(metadata).get("result") or {}
    for item in result.get("distribution") or []:
        if str(item.get("resourceFormat", "")).upper() == "ZIP" and item.get("resourceDownloadUrl"):
            return str(item["resourceDownloadUrl"])
    raise ValueError("data.gov.tw 6099 lists no ZIP distribution")


@register_provider
class NdcProvider(MacroReleaseProvider):
    name: ClassVar[str] = "ndc"
    min_interval: ClassVar[float] = 3.0
    macro_codes: ClassVar[frozenset[str]] = frozenset(COLUMNS)

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or make_client()

    def fetch_macro_release(self) -> RawResponse:
        url = download_url(get_json_bytes(self.client, DATASET_URL))
        body = get_bytes(self.client, url)
        return RawResponse("business_indicators", body, {"dataset": "6099", "url": url})

    def parse_macro_release(self, raw: RawResponse) -> list[SeriesObservation]:
        payload = raw.payload
        if not isinstance(payload, bytes):
            raise ValueError("NDC release: expected ZIP bytes")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            texts = [archive.read(info).decode("utf-8-sig") for info in archive.infolist()]
        # File names are Big5/UTF-8 mixed across releases; find the table by its header.
        table = next((t for t in texts if SIGNAL_COLUMN in t.partition("\n")[0]), None)
        if table is None:
            raise ValueError(f"no CSV with {SIGNAL_COLUMN} in the NDC release")
        rows = csv.reader(io.StringIO(table))
        header = {name.strip(): i for i, name in enumerate(next(rows))}
        missing = {"Date", LIGHT_COLUMN, *COLUMNS.values()} - set(header)
        if missing:
            raise ValueError(f"NDC table lacks columns {sorted(missing)}")
        out = []
        for cells in rows:
            if not cells:
                continue
            stamp = cells[header["Date"]].strip()
            month = date(int(stamp[:4]), int(stamp[4:6]), 1)
            light = cells[header[LIGHT_COLUMN]].strip()
            for code, column in COLUMNS.items():
                text = clean_number(cells[header[column]])
                if text is None:  # '-' before the series started (the signal began in 1984)
                    continue
                label = None
                if code == "TW_SIGNAL":
                    if light not in LIGHTS:
                        raise ValueError(f"unknown light {light!r} in {stamp}")
                    label = f"{light}燈"
                out.append(
                    SeriesObservation(code=code, obs_date=month, value=Decimal(text), label=label)
                )
        if not out:
            raise ValueError("no observations parsed from the NDC release")
        return out
