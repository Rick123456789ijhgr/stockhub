"""Shared HTTP plumbing for official data sources: identify ourselves, classify failures."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from stockhub.etl.providers.base import (
    PermanentProviderError,
    TransientProviderError,
    preview_action_type,
)

USER_AGENT = "StockHub/0.1 (personal non-commercial research; rate-limited)"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.8"},
        timeout=TIMEOUT,
        follow_redirects=True,
        transport=transport,
    )


def get_bytes(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> bytes:
    """GET a URL; 5xx/429/network errors are transient, other 4xx permanent."""
    try:
        response = client.get(url, params=params)
    except httpx.TimeoutException as exc:
        raise TransientProviderError(f"timeout: {url}") from exc
    except httpx.TransportError as exc:
        raise TransientProviderError(f"network error: {exc}") from exc
    if response.status_code == 429 or response.status_code >= 500:
        raise TransientProviderError(f"HTTP {response.status_code} from {url}")
    if response.status_code >= 400:
        raise PermanentProviderError(f"HTTP {response.status_code} from {url}")
    return response.content


def get_json_bytes(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> bytes:
    """Like get_bytes, but an HTML page instead of JSON (e.g. a throttling notice) is transient."""
    body = get_bytes(client, url, params)
    if body.lstrip()[:1] not in (b"{", b"["):
        raise TransientProviderError(f"non-JSON response from {url} (throttled?)")
    return body


def clean_number(value: str | None) -> str | None:
    """'1,234.50' -> '1234.50'; placeholders such as '--', '----', '' -> None."""
    if value is None:
        return None
    text = value.replace(",", "").strip()
    if not text or set(text) <= {"-", "+", " "} or text in {"X", "除權", "除息"}:
        return None
    return text


def maybe_decimal(value: str | None) -> Decimal | None:
    """Like clean_number, but notes in number columns ('尚未公告', '註4') become None too."""
    text = clean_number(value)
    if text is None:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def preview_fields(
    label: str, cash: str | None, stock_ratio: str | None, rights: str | None, price: str | None
) -> dict[str, Any]:
    """Shared normalization of both exchanges' 除權除息預告 rows.

    The label loses its 除 prefix (TPEx writes 除權息, TWSE 權息). A 息 event whose cash is
    blank or 0 has not announced its amount yet (cash None), which ETFs often do late.
    """
    tag = label.strip().removeprefix("除")
    if tag not in ("息", "權", "權息"):
        raise ValueError(f"unknown ex-rights label {label!r}")
    amount = maybe_decimal(cash)
    if amount == 0 and "息" in tag:
        amount = None
    ratio = maybe_decimal(stock_ratio) or Decimal(0)
    offering = maybe_decimal(rights) or Decimal(0)
    sub_price = maybe_decimal(price)
    return {
        "label": tag,
        "action_type": preview_action_type(tag, amount, ratio, offering),
        "cash_dividend": amount,
        "stock_dividend_ratio": ratio,
        "rights_ratio": offering,
        "subscription_price": sub_price if sub_price and sub_price > 0 else None,
    }


def roc_date(value: str) -> date:
    """Parse the exchanges' Minguo dates: '115/09/01', '115-10-16', '114年06月02日', '1140113'.

    Gregorian dates ('2026/10/16', '20261016') pass through, so callers need not care which
    calendar an endpoint uses.
    """
    text = value.strip().replace("年", "/").replace("月", "/").replace("日", "").replace("-", "/")
    if "/" in text:
        year, month, day = (int(part) for part in text.split("/"))
    elif text.isdigit() and len(text) in (7, 8):
        year, month, day = int(text[:-4]), int(text[-4:-2]), int(text[-2:])
    else:
        raise ValueError(f"unrecognized date {value!r}")
    return date(year + 1911 if year < 1000 else year, month, day)


ROBOTS_TTL = 12 * 3600.0


class RobotsCache:
    """robots.txt per host, read once per ROBOTS_TTL (rule 12). A missing robots.txt (4xx)
    allows everything; one that cannot be read (5xx, network) is transient."""

    def __init__(self, client: httpx.Client, clock: Callable[[], float] = time.monotonic) -> None:
        self.client, self._clock = client, clock
        self._parsers: dict[str, tuple[float, RobotFileParser]] = {}

    def allowed(self, url: str, agent: str = "StockHub") -> bool:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        cached = self._parsers.get(host)
        if cached is None or self._clock() - cached[0] > ROBOTS_TTL:
            parser = RobotFileParser()
            try:
                response = self.client.get(f"{host}/robots.txt")
            except httpx.TransportError as exc:
                raise TransientProviderError(f"robots.txt of {host}: {exc}") from exc
            if response.status_code >= 500:
                raise TransientProviderError(f"robots.txt of {host}: HTTP {response.status_code}")
            lines = response.text.splitlines() if response.status_code < 400 else []
            parser.parse(lines)
            cached = (self._clock(), parser)
            self._parsers[host] = cached
        return cached[1].can_fetch(agent, url)
