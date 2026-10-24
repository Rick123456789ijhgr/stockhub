"""Any RSS 2.0 or Atom feed (news_sources.kind = 'rss'): Yahoo 股市, 經濟日報, 工商時報 and
whatever the user adds on /admin (D-135).

Only what the feed itself carries is used: title, link, date and the description, which is
clipped to a snippet. Article pages are never fetched (D-138). Feeds disagree on dates
(RFC 822 with a zone, ISO 8601 without one); a date without a zone is Taipei time, and an
item without a usable date takes the fetch time.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import ClassVar

import httpx

from stockhub.common.timeutil import TAIPEI, utcnow
from stockhub.engine.news import clip, html_to_text, normalize_url, one_line
from stockhub.etl.providers.base import (
    NewsItem,
    NewsKind,
    NewsProvider,
    NewsRequest,
    PermanentProviderError,
    RawResponse,
)
from stockhub.etl.providers.http import get_bytes, make_client
from stockhub.etl.providers.registry import register_provider

ATOM = "{http://www.w3.org/2005/Atom}"
MAX_ITEMS = 100
"""Feeds list their newest items first; more than this per fetch is not news any more."""


def parse_feed_date(value: str | None, fallback: datetime) -> datetime:
    """RFC 822 ('Sat, 24 Oct 2026 13:30:37 GMT') or ISO 8601 ('2026-10-24T15:14:29');
    naive values are Taipei time; unparseable or missing values fall back."""
    if not value or not value.strip():
        return fallback
    text = value.strip()
    parsed: datetime | None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=TAIPEI)


def _text(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def parse_feed(payload: bytes, fetched_at: datetime, symbol: str | None = None) -> list[NewsItem]:
    root = ET.fromstring(payload)  # noqa: S314 - see the import
    entries: list[tuple[str, str, str, str, str]] = []  # id, link, title, date, summary
    if root.tag == f"{ATOM}feed":
        for entry in root.findall(f"{ATOM}entry"):
            link = ""
            for node in entry.findall(f"{ATOM}link"):
                if node.get("rel", "alternate") == "alternate" and node.get("href"):
                    link = node.get("href", "")
                    break
            date = _text(entry.find(f"{ATOM}published")) or _text(entry.find(f"{ATOM}updated"))
            summary = _text(entry.find(f"{ATOM}summary")) or _text(entry.find(f"{ATOM}content"))
            title = _text(entry.find(f"{ATOM}title"))
            entries.append((_text(entry.find(f"{ATOM}id")), link, title, date, summary))
    else:
        channel = root.find("channel")
        if channel is None:
            raise ValueError(f"not an RSS or Atom feed (root <{root.tag}>)")
        for item in channel.findall("item"):
            # A guid is an opaque id unless it is the article URL (isPermaLink defaults to
            # true, but feeds such as 工商時報 put plain ids there without the attribute).
            guid = _text(item.find("guid"))
            is_url = guid.startswith(("http://", "https://"))
            entries.append(
                (
                    "" if is_url else guid,
                    _text(item.find("link")) or (guid if is_url else ""),
                    _text(item.find("title")),
                    _text(item.find("pubDate")),
                    _text(item.find("description")),
                )
            )
    out = []
    for guid, link, title, date, summary in entries[:MAX_ITEMS]:
        title = one_line(html_to_text(title))
        if not title or not link.startswith(("http://", "https://")):
            continue
        url = normalize_url(link)
        out.append(
            NewsItem(
                external_id=guid or url,
                url=url,
                title=title,
                snippet=clip(html_to_text(summary)),
                published_at=parse_feed_date(date, fetched_at),
                symbols=[symbol] if symbol else [],
            )
        )
    return out


@register_provider
class RssProvider(NewsProvider):
    name: ClassVar[str] = "rss"
    min_interval: ClassVar[float] = 1.0
    news_kinds: ClassVar[frozenset[NewsKind]] = frozenset({"rss"})

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or make_client()

    def fetch_news(self, request: NewsRequest) -> RawResponse:
        if not request.url:
            raise PermanentProviderError(f"rss source {request.source} has no URL")
        body = get_bytes(self.client, request.url)
        return RawResponse(
            "feed",
            body,
            {
                "source": request.source,
                "url": request.url,
                "symbol": request.symbol,
                "fetched_at": utcnow().isoformat(),
            },
        )

    def parse_news(self, raw: RawResponse) -> list[NewsItem]:
        payload = raw.payload
        data = payload.encode() if isinstance(payload, str) else payload
        return parse_feed(
            data, datetime.fromisoformat(raw.params["fetched_at"]), raw.params.get("symbol")
        )
