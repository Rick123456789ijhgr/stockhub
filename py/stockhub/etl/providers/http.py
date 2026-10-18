"""Shared HTTP plumbing for official data sources: identify ourselves, classify failures."""

from __future__ import annotations

from typing import Any

import httpx

from stockhub.etl.providers.base import PermanentProviderError, TransientProviderError

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
