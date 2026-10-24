"""PTT 股票板 [標的] posts (news_sources.kind = 'ptt'); www.ptt.cc has no robots.txt.

One fetch reads the board search for [標的] (newest first, a few pages until posts are older
than MAX_AGE), then the page of each new original post (replies are skipped) that is at
least MIN_AGE old, so its 推/噓 counts have mostly settled. All pages of the fetch are
bundled into one raw object; a post's text is only read while processing and the raw
object is purged after 30 days (D-138). One request per PAGE_DELAY seconds.

Article ids are M.{epoch}.A.{hash}: the epoch is the posting time.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
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
from stockhub.etl.providers.http import get_bytes, make_client
from stockhub.etl.providers.registry import register_provider

TAG = "[標的]"
MIN_AGE = timedelta(hours=2)
MAX_AGE = timedelta(days=3)
MAX_PAGES = 3
MAX_ARTICLES = 20
PAGE_DELAY = 1.0
BODY_CHARS = 4000
"""Text handed to the LLM per post."""

_ENTRY = re.compile(r'<div class="r-ent">(.*?)<div class="mark">', re.S)
_LINK = re.compile(r'<a href="(/bbs/[^/"]+/(M\.\d+\.A\.[0-9A-F]+)\.html)">(.*?)</a>', re.S)
_NREC = re.compile(r'<div class="nrec">(?:<span[^>]*>)?([^<]*)')
_AUTHOR = re.compile(r'<div class="author">([^<]*)</div>')
_META = re.compile(
    r'<span class="article-meta-tag">(.*?)</span><span class="article-meta-value">(.*?)</span>',
    re.S,
)
_METALINE = re.compile(r'<div class="article-metaline(?:-right)?">.*?</div>', re.S)
_PUSH_TAG = re.compile(r'<span class="[^"]*push-tag">(.*?)</span>')


def posted_at(article_id: str) -> datetime:
    """M.1792711156.A.6AC -> 2026-10-22 23:19:16 UTC."""
    return datetime.fromtimestamp(int(article_id.split(".")[1]), UTC)


def parse_list(page: str) -> list[dict[str, Any]]:
    """Entries of a board index or search page (deleted posts have no link and are skipped)."""
    out = []
    for block in _ENTRY.findall(page):
        link = _LINK.search(block)
        if link is None:
            continue
        nrec = _NREC.search(block)
        author = _AUTHOR.search(block)
        out.append(
            {
                "path": link.group(1),
                "id": link.group(2),
                "title": one_line(html_to_text(link.group(3))),
                "nrec": nrec.group(1).strip() if nrec else "",
                "author": author.group(1).strip() if author else "",
            }
        )
    return out


def wanted(entry: dict[str, Any], known: frozenset[str], now: datetime) -> bool:
    if not str(entry["title"]).startswith(TAG) or entry["id"] in known:
        return False
    age = now - posted_at(entry["id"])
    return MIN_AGE <= age <= MAX_AGE


def parse_article(article_id: str, page: str, board_url: str) -> NewsItem | None:
    meta = {html_to_text(k): html_to_text(v) for k, v in _META.findall(page)}
    start = page.find('<div id="main-content"')
    if start < 0:
        return None
    end = page.find('<div class="push">', start)
    content = page[start : end if end > 0 else len(page)]
    text = html_to_text(_METALINE.sub("", content))
    # Drop the signature and the 發信站 footer.
    for marker in ("\n--\n※ 發信站", "\n※ 發信站"):
        cut = text.find(marker)
        if cut >= 0:
            text = text[:cut]
    tags = [html_to_text(t).strip() for t in _PUSH_TAG.findall(page)]
    title = one_line(meta.get("標題", ""))
    if not title:
        return None
    return NewsItem(
        external_id=article_id,
        url=f"{board_url}{article_id}.html",
        title=title,
        published_at=posted_at(article_id),
        meta={
            "author": meta.get("作者", "").split(" ")[0] or None,
            "pushes": tags.count("推"),
            "boos": tags.count("噓"),
            "arrows": tags.count("→"),
        },
        body=clip(text.strip(), BODY_CHARS),
    )


@register_provider
class PttProvider(NewsProvider):
    name: ClassVar[str] = "ptt"
    min_interval: ClassVar[float] = 1.0
    news_kinds: ClassVar[frozenset[NewsKind]] = frozenset({"ptt"})

    def __init__(
        self,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.client = client or make_client()
        self.client.cookies.set("over18", "1", domain="www.ptt.cc")
        self._sleep, self._clock = sleep, clock

    def _get(self, url: str, params: dict[str, Any] | None = None) -> str:
        self._sleep(PAGE_DELAY)
        return get_bytes(self.client, url, params).decode("utf-8", errors="replace")

    def fetch_news(self, request: NewsRequest) -> RawResponse:
        if not request.url:
            raise PermanentProviderError(f"ptt source {request.source} has no URL")
        board_url = request.url.rsplit("/", 1)[0] + "/"
        origin = board_url.split("/bbs/", 1)[0]
        now = self._clock()
        entries: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            found = parse_list(self._get(board_url + "search", {"q": TAG, "page": page}))
            entries.extend(found)
            if not found or min(posted_at(e["id"]) for e in found) < now - MAX_AGE:
                break
        articles: dict[str, str] = {}
        for entry in [e for e in entries if wanted(e, request.known, now)][:MAX_ARTICLES]:
            try:
                articles[entry["id"]] = self._get(origin + entry["path"])
            except PermanentProviderError:  # deleted between listing and reading
                continue
        payload = {"list": entries, "articles": articles}
        return RawResponse(
            "posts",
            json.dumps(payload, ensure_ascii=False),
            {"source": request.source, "board": board_url, "fetched_at": now.isoformat()},
        )

    def parse_news(self, raw: RawResponse) -> list[NewsItem]:
        payload = raw.payload
        data = json.loads(payload) if isinstance(payload, bytes | str) else payload
        board_url = raw.params["board"]
        nrec = {e["id"]: e.get("nrec") for e in data.get("list", [])}
        out = []
        for article_id, page in data.get("articles", {}).items():
            item = parse_article(article_id, page, board_url)
            if item is not None:
                item.meta["nrec"] = nrec.get(article_id) or None
                out.append(item)
        return out
