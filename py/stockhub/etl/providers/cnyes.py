"""鉅亨網 news list (news.cnyes.com/api/v3/news/category/{category}): an unofficial JSON API
the site's own pages use; robots.txt allows it (D-135). Rate-limited like any page.

Each item carries newsId, title, an editor's summary, publishAt (epoch seconds) and the
stocks the newsroom tagged (market[].code, TW stocks as TWS:2330:STOCK).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from stockhub.common.timeutil import utcnow
from stockhub.engine.news import clip, html_to_text, one_line
from stockhub.etl.providers.base import (
    NewsItem,
    NewsKind,
    NewsProvider,
    NewsRequest,
    PermanentProviderError,
    RawResponse,
)
from stockhub.etl.providers.http import get_json_bytes, make_client
from stockhub.etl.providers.registry import register_provider

ARTICLE_URL = "https://news.cnyes.com/news/id/{id}"
PAGE_SIZE = 30


def _tw_symbols(item: dict[str, Any]) -> list[str]:
    symbols = []
    for tag in item.get("market") or []:
        symbol = str(tag.get("symbol") or "")
        code = str(tag.get("code") or "").strip()
        if symbol.startswith("TWS:") and code and code not in symbols:
            symbols.append(code)
    return symbols


def parse_cnyes(payload: bytes | str | Any) -> list[NewsItem]:
    data = json.loads(payload) if isinstance(payload, bytes | str) else payload
    rows = ((data.get("items") or {}).get("data")) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("cnyes answer without items.data")
    out = []
    for row in rows:
        news_id, title = row.get("newsId"), one_line(html_to_text(row.get("title")))
        stamp = row.get("publishAt")
        if not news_id or not title or not isinstance(stamp, int | float):
            continue
        out.append(
            NewsItem(
                external_id=str(news_id),
                url=ARTICLE_URL.format(id=news_id),
                title=title,
                snippet=clip(html_to_text(row.get("summary"))),
                published_at=datetime.fromtimestamp(stamp, UTC),
                symbols=_tw_symbols(row),
                meta={"keywords": [str(k) for k in row.get("keyword") or []][:10]},
            )
        )
    return out


@register_provider
class CnyesProvider(NewsProvider):
    name: ClassVar[str] = "cnyes"
    min_interval: ClassVar[float] = 2.0
    news_kinds: ClassVar[frozenset[NewsKind]] = frozenset({"cnyes"})

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or make_client()

    def fetch_news(self, request: NewsRequest) -> RawResponse:
        if not request.url:
            raise PermanentProviderError(f"cnyes source {request.source} has no URL")
        body = get_json_bytes(self.client, request.url, {"limit": PAGE_SIZE})
        return RawResponse(
            "news",
            body,
            {"source": request.source, "url": request.url, "fetched_at": utcnow().isoformat()},
        )

    def parse_news(self, raw: RawResponse) -> list[NewsItem]:
        return parse_cnyes(raw.payload)
