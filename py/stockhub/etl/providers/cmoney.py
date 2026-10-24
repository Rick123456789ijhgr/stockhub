"""CMoney 股市爆料同學會 posts (news_sources.kind = 'cmoney_forum'); robots.txt allows /forum.

The popular page (forum/popular/buzz?tab=popular) is rendered on the server and links the
posts it shows (/forum/article/{id}); each post page carries its publication time in
<meta property="article:published_time">, the stock tags with the author's own 看多/看空
(stockTagLabel__stance--bull / --bear), the text and the reaction counts. Per-stock pages
load their posts through an internal API, which we do not use (D-143).

One fetch reads the popular page and the pages of posts not stored yet, bundled into one raw
object that is purged after 30 days like PTT (D-138). One request per PAGE_DELAY seconds.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import datetime
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
    Stance,
)
from stockhub.etl.providers.http import get_bytes, make_client
from stockhub.etl.providers.registry import register_provider

ORIGIN = "https://www.cmoney.tw"
ARTICLE_URL = ORIGIN + "/forum/article/{id}"
MAX_ARTICLES = 15
PAGE_DELAY = 1.0
BODY_CHARS = 4000
TITLE_CHARS = 80

_ARTICLE_LINK = re.compile(r'href="/forum/article/(\d+)"')
_PUBLISHED = re.compile(r'property="article:published_time" content="([^"]+)"')
_TAG_ITEM = re.compile(r'<li class="articleTags__item".*?</li>', re.S)
_TAG_STOCK = re.compile(r'href="/forum/stock/([0-9A-Z]+)"')
_TAG_STANCE = re.compile(r"stockTagLabel__stance--(bull|bear)")
_TEXT = re.compile(r'<pre class="textRule__text[^"]*"[^>]*>(.*?)</pre>', re.S)
_LIKES = re.compile(r"articleResponse__number[^>]*>\s*([\d,]+)\s*<")
_COMMENTS = re.compile(r"([\d,]+)則留言")
_TW_SYMBOL = re.compile(r"^\d{4,6}[A-Z]?$")
_ISO_HOUR = re.compile(r"T(\d):")


def article_ids(page: str) -> list[str]:
    """Post ids linked from a list page, in page order, without repeats."""
    seen: dict[str, None] = {}
    for article_id in _ARTICLE_LINK.findall(page):
        seen.setdefault(article_id, None)
    return list(seen)


def parse_published(value: str) -> datetime:
    """'2026-10-24T5:58:44+08:00' (hours are not zero-padded) -> aware datetime."""
    return datetime.fromisoformat(_ISO_HOUR.sub(r"T0\1:", value.strip()))


def parse_post(article_id: str, page: str) -> NewsItem | None:
    published = _PUBLISHED.search(page)
    if published is None:
        return None
    # The post itself comes first; recommended posts further down have tags of their own.
    start = page.find("articleContent__wrapper")
    end = page.find("articleContent__foot", start)
    block = page[start:end] if start >= 0 and end > start else page
    symbols: list[str] = []
    stances: dict[str, Stance] = {}
    for tag in _TAG_ITEM.findall(block):
        stock = _TAG_STOCK.search(tag)
        if stock is None or not _TW_SYMBOL.match(stock.group(1)):
            continue
        symbol = stock.group(1)
        if symbol not in symbols:
            symbols.append(symbol)
        stance = _TAG_STANCE.search(tag)
        if stance:
            stances[symbol] = "bullish" if stance.group(1) == "bull" else "bearish"
    text_match = _TEXT.search(block)
    text = html_to_text(text_match.group(1)) if text_match else ""
    if not text:
        return None
    likes = _LIKES.search(block)
    comments = _COMMENTS.search(block)
    return NewsItem(
        external_id=article_id,
        url=ARTICLE_URL.format(id=article_id),
        title=clip(one_line(text), TITLE_CHARS) or text[:TITLE_CHARS],
        published_at=parse_published(published.group(1)),
        symbols=symbols,
        stances=stances,
        meta={
            "likes": int(likes.group(1).replace(",", "")) if likes else 0,
            "comments": int(comments.group(1).replace(",", "")) if comments else 0,
        },
        body=clip(text, BODY_CHARS),
    )


@register_provider
class CmoneyForumProvider(NewsProvider):
    name: ClassVar[str] = "cmoney"
    min_interval: ClassVar[float] = 1.0
    news_kinds: ClassVar[frozenset[NewsKind]] = frozenset({"cmoney_forum"})

    def __init__(
        self, client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        self.client = client or make_client()
        self._sleep = sleep

    def _get(self, url: str) -> str:
        self._sleep(PAGE_DELAY)
        return get_bytes(self.client, url).decode("utf-8", errors="replace")

    def fetch_news(self, request: NewsRequest) -> RawResponse:
        if not request.url:
            raise PermanentProviderError(f"cmoney source {request.source} has no URL")
        ids = article_ids(self._get(request.url))
        articles: dict[str, str] = {}
        for article_id in [i for i in ids if i not in request.known][:MAX_ARTICLES]:
            try:
                articles[article_id] = self._get(ARTICLE_URL.format(id=article_id))
            except PermanentProviderError:  # removed since the list was rendered
                continue
        return RawResponse(
            "posts",
            json.dumps({"list": ids, "articles": articles}, ensure_ascii=False),
            {"source": request.source, "url": request.url, "fetched_at": utcnow().isoformat()},
        )

    def parse_news(self, raw: RawResponse) -> list[NewsItem]:
        payload = raw.payload
        data: dict[str, Any] = json.loads(payload) if isinstance(payload, bytes | str) else payload
        out = []
        for article_id, page in data.get("articles", {}).items():
            item = parse_post(article_id, page)
            if item is not None:
                out.append(item)
        return out
