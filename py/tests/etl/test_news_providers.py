"""News sources (M6): exchange announcements, RSS, 鉅亨網, PTT and CMoney forum adapters."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine

from stockhub.common.rawstore import LocalRawStore
from stockhub.common.timeutil import TAIPEI
from stockhub.etl.providers.base import NewsRequest, PermanentProviderError, RawResponse
from stockhub.etl.providers.cmoney import (
    CmoneyForumProvider,
    article_ids,
    parse_post,
    parse_published,
)
from stockhub.etl.providers.cnyes import CnyesProvider
from stockhub.etl.providers.http import make_client
from stockhub.etl.providers.ptt import PttProvider, parse_list, posted_at
from stockhub.etl.providers.rss import RssProvider, parse_feed, parse_feed_date
from stockhub.etl.providers.tpex import TpexProvider
from stockhub.etl.providers.twse import TwseProvider

from .official_sources import PTT_NOW, fixture, official_handler, official_router

FETCHED = datetime(2026, 10, 25, tzinfo=UTC)


def _client() -> httpx.Client:
    return make_client(httpx.MockTransport(official_handler))


def _mops(market: str) -> NewsRequest:
    return NewsRequest(source=f"mops_{market}", kind="mops", url=None, market=market)  # type: ignore[arg-type]


def test_announcements_from_both_exchanges() -> None:
    twse, tpex = TwseProvider(_client()), TpexProvider(_client())
    assert twse.serves(_mops("twse"))
    assert not twse.serves(_mops("tpex"))
    assert tpex.serves(_mops("tpex"))
    raw = twse.fetch_news(_mops("twse"))
    assert raw.params["source"] == "mops_twse"
    items = twse.parse_news(raw)
    assert [i.symbols for i in items] == [["2072"], ["6949"], ["2514"]]
    first = items[0]
    assert first.title.startswith("公告本公司名稱由「世紀離岸風電設備股份有限公司」更名 為")
    assert first.published_at == datetime(2026, 10, 21, 7, 0, 4, tzinfo=TAIPEI)
    assert first.external_id.startswith("2072-1151021-70004-")
    assert first.url.endswith("companyId=2072")
    assert first.meta["company"]
    assert {k: first.meta[k] for k in ("market", "clause", "factDate")} == {
        "market": "twse",
        "clause": "第51款",
        "factDate": "2026-08-24",
    }
    assert first.snippet is not None
    assert len(first.snippet) <= 500
    assert first.body is not None
    assert first.body.startswith(first.title + "\n1.事實發生日")
    otc = tpex.parse_news(tpex.fetch_news(_mops("tpex")))
    assert [(i.symbols, i.meta["clause"]) for i in otc] == [
        (["4747"], "第53款"),
        (["6242"], "第26款"),
    ]
    assert otc[1].published_at == datetime(2026, 10, 21, 9, 4, 22, tzinfo=TAIPEI)


def test_announcement_ids_differ_for_two_subjects_in_one_second() -> None:
    row = {"發言日期": "1151021", "發言時間": "70004", "公司代號": "2330", "說明": ""}
    from stockhub.etl.providers.mops_openapi import parse_announcements

    items = parse_announcements([{**row, "主旨 ": "甲"}, {**row, "主旨 ": "乙"}, row], "twse")
    assert len(items) == 2  # a row without a subject is skipped
    assert items[0].external_id != items[1].external_id
    assert items[0].body == "甲"


def test_rss_feeds_with_zones_and_per_stock_symbol() -> None:
    rss = RssProvider(_client())
    request = NewsRequest(
        source="yahoo_stock",
        kind="rss",
        url="https://tw.stock.yahoo.com/rss?s=6488.TWO",
        symbol="6488",
    )
    items = rss.parse_news(rss.fetch_news(request))
    assert len(items) == 2
    assert all(i.symbols == ["6488"] for i in items)
    assert items[0].title.startswith("【公告】環球晶代子公司")
    assert items[0].published_at == datetime(2026, 10, 23, 7, 28, 2, tzinfo=UTC)
    assert items[0].external_id == items[0].url  # empty guid: the URL identifies it
    ctee = parse_feed(fixture("rss_ctee_stock.xml"), FETCHED)
    # 工商時報 dates carry no zone: Taipei time.
    assert ctee[0].published_at == datetime(2026, 10, 24, 15, 14, 29, tzinfo=TAIPEI)
    assert ctee[0].external_id == "20261024700515"
    assert ctee[0].symbols == []
    udn = parse_feed(fixture("rss_udn_stock.xml"), FETCHED)
    assert udn[0].url == "https://money.udn.com/money/story/5607/9833556"
    assert udn[0].published_at == datetime(2026, 10, 24, 18, 42, 26, tzinfo=TAIPEI)


def test_atom_feed_and_bad_entries() -> None:
    atom = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>tag:a,1</id><title>A &amp; B</title>
    <link rel="alternate" href="https://a.example/x?utm_source=rss&amp;id=2"/>
    <published>2026-10-24T01:02:03Z</published><summary>&lt;p&gt;hello&lt;/p&gt;</summary></entry>
  <entry><id>tag:a,2</id><title>no link</title></entry>
  <entry><id>tag:a,3</id><title> </title><link href="https://a.example/y"/></entry>
</feed>"""
    items = parse_feed(atom, FETCHED)
    assert len(items) == 1
    assert items[0].title == "A & B"
    assert items[0].url == "https://a.example/x?id=2"
    assert items[0].external_id == "tag:a,1"
    assert items[0].snippet == "hello"
    with pytest.raises(ValueError, match="not an RSS"):
        parse_feed(b"<html><body/></html>", FETCHED)


def test_feed_dates() -> None:
    assert parse_feed_date("Sat, 24 Oct 2026 13:30:37 GMT", FETCHED) == datetime(
        2026, 10, 24, 13, 30, 37, tzinfo=UTC
    )
    assert parse_feed_date("2026-10-24T15:14:29+08:00", FETCHED) == datetime(
        2026, 10, 24, 7, 14, 29, tzinfo=UTC
    )
    assert parse_feed_date("someday", FETCHED) == FETCHED
    assert parse_feed_date(None, FETCHED) == FETCHED


def test_cnyes_items_and_tw_tags() -> None:
    cnyes = CnyesProvider(_client())
    request = NewsRequest(
        source="cnyes_tw_stock",
        kind="cnyes",
        url="https://news.cnyes.com/api/v3/news/category/tw_stock",
    )
    items = cnyes.parse_news(cnyes.fetch_news(request))
    assert [i.external_id for i in items] == ["6637127", "6637225"]
    assert items[0].url == "https://news.cnyes.com/news/id/6637127"
    assert items[0].symbols == ["6902"]
    assert items[0].snippet is not None
    assert items[0].snippet.startswith("GOGOLOOK受海外市場擴張")
    assert items[0].published_at == datetime(2026, 10, 24, 13, 18, 53, tzinfo=UTC)
    assert items[1].symbols == []
    with pytest.raises(ValueError, match=r"items.data"):
        cnyes.parse_news(RawResponse("news", b'{"status": 500}'))


def test_ptt_reads_only_new_settled_target_posts() -> None:
    entries = parse_list(fixture("ptt_search.html").decode())
    assert len(entries) == 20
    assert entries[0]["id"] == "M.1792711156.A.6AC"
    assert entries[0]["nrec"] == "17"
    assert posted_at("M.1792711156.A.6AC") == datetime(2026, 10, 22, 23, 19, 16, tzinfo=UTC)

    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return official_handler(request)

    client = make_client(httpx.MockTransport(handler))
    ptt = PttProvider(client, sleep=lambda _: None, clock=lambda: PTT_NOW)
    request = NewsRequest(
        source="ptt_stock", kind="ptt", url="https://www.ptt.cc/bbs/Stock/index.html"
    )
    raw = ptt.fetch_news(request)
    articles = [p for p in requested if "/M." in p]
    # Only [標的] originals 2 h to 3 days old: no replies, nothing older than the window.
    assert "/bbs/Stock/M.1792711156.A.6AC.html" in articles
    assert all(
        timedelta(hours=2) <= PTT_NOW - posted_at(p.rsplit("/", 1)[-1].removesuffix(".html"))
        for p in articles
    )
    items = ptt.parse_news(raw)
    assert len(items) == 1  # the other pages answered 404 (deleted)
    post = items[0]
    assert post.title == "[標的] SOXS 三倍反向半導體 無腦加碼多"
    assert post.url == "https://www.ptt.cc/bbs/Stock/M.1792711156.A.6AC.html"
    assert post.meta == {
        "author": "andylu1207",
        "pushes": 20,
        "boos": 3,
        "arrows": 11,
        "category": "加碼多",
        "stance": "bullish",
        "nrec": "17",
    }
    assert post.body is not None
    assert post.body.startswith("標的：SOXS.US 3倍反向費半")
    assert "發信站" not in post.body
    assert post.snippet is None

    requested.clear()
    known = NewsRequest(
        source="ptt_stock",
        kind="ptt",
        url="https://www.ptt.cc/bbs/Stock/index.html",
        known=frozenset({"M.1792711156.A.6AC"}),
    )
    ptt.fetch_news(known)
    assert "/bbs/Stock/M.1792711156.A.6AC.html" not in requested


def test_ptt_category_stance() -> None:
    from stockhub.etl.providers.ptt import stance_of

    assert stance_of("多") == "bullish"
    assert stance_of("加碼空") == "bearish"
    assert stance_of("多空") is None
    assert stance_of("討論") is None
    assert stance_of(None) is None


def test_cmoney_forum_posts_with_author_stance() -> None:
    assert article_ids(fixture("cmoney_popular.html").decode())[:2] == ["186735158", "186740658"]
    assert parse_published("2026-10-24T5:58:44+08:00") == datetime(
        2026, 10, 24, 5, 58, 44, tzinfo=TAIPEI
    )
    forum = CmoneyForumProvider(_client(), sleep=lambda _: None)
    request = NewsRequest(
        source="cmoney_forum",
        kind="cmoney_forum",
        url="https://www.cmoney.tw/forum/popular/buzz?tab=popular",
        known=frozenset({"186735158"}),
    )
    raw = forum.fetch_news(request)
    data = json.loads(raw.payload)
    assert len(data["list"]) == 10
    assert "186735158" not in data["articles"]
    items = forum.parse_news(raw)
    assert len(items) == 1
    post = items[0]
    assert post.external_id == "186740658"
    assert post.url == "https://www.cmoney.tw/forum/article/186740658"
    # The recommended post below the article (2330 看空) is not part of it.
    assert post.symbols == ["00406A"]
    assert post.stances == {"00406A": "bullish"}
    assert post.published_at == datetime(2026, 10, 24, 21, 29, 41, tzinfo=TAIPEI)
    assert post.meta == {"likes": 40, "comments": 7}
    assert post.title.startswith("客觀看數據，理性作分享")
    assert len(post.title) <= 80
    assert post.body is not None
    assert "406a的規模" in post.body
    assert parse_post("1", "<html></html>") is None


def test_sources_without_url_are_permanent_errors() -> None:
    for provider, kind in (
        (RssProvider(_client()), "rss"),
        (CnyesProvider(_client()), "cnyes"),
        (PttProvider(_client(), sleep=lambda _: None), "ptt"),
        (CmoneyForumProvider(_client(), sleep=lambda _: None), "cmoney_forum"),
    ):
        with pytest.raises(PermanentProviderError):
            provider.fetch_news(NewsRequest(source="x", kind=kind, url=None))  # type: ignore[arg-type]


def test_router_lands_news_in_rawstore(engine: Engine, tmp_path: Path) -> None:
    router = official_router(LocalRawStore(engine, tmp_path))
    fetched = router.news(_mops("tpex"))
    assert fetched.provider == "tpex"
    assert len(fetched.items) == 2
    assert fetched.raw.uri.startswith("file://")
    feed = router.news(
        NewsRequest(
            source="ctee_stock", kind="rss", url="https://www.ctee.com.tw/rss_web/livenews/stock"
        )
    )
    assert feed.provider == "rss"
    assert len(feed.items) == 2


def test_rss_respects_robots_txt() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            if request.url.host == "down.example":
                return httpx.Response(503)
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        return httpx.Response(200, content=fixture("rss_ctee_stock.xml"))

    rss = RssProvider(make_client(httpx.MockTransport(handler)))
    ok = NewsRequest(source="a", kind="rss", url="https://feeds.example/rss/stock")
    assert len(rss.parse_news(rss.fetch_news(ok))) == 2
    blocked = NewsRequest(source="b", kind="rss", url="https://feeds.example/private/rss")
    with pytest.raises(PermanentProviderError, match="robots"):
        rss.fetch_news(blocked)
    from stockhub.etl.providers.base import TransientProviderError

    with pytest.raises(TransientProviderError):
        rss.fetch_news(NewsRequest(source="c", kind="rss", url="https://down.example/rss"))
