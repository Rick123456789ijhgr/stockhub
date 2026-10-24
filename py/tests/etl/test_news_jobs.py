"""News jobs end to end against recorded sources (no network) and a scripted LLM."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text

from stockhub.common.llm import Completion, LLMRouter, LLMService
from stockhub.common.notifier import Notifier, Severity
from stockhub.common.rawstore import LocalRawStore
from stockhub.common.timeutil import TAIPEI
from stockhub.etl.jobs.base import Job, JobRunResult, run_job
from stockhub.etl.jobs.news import NewsSettings, Source, requests_for

from .official_sources import PTT_NOW, official_router

ANNOUNCEMENT_DAY = datetime(2026, 10, 21, 10, 0, tzinfo=TAIPEI)
YAHOO_DAY = datetime(2026, 10, 23, 8, 0, tzinfo=TAIPEI)


class ScriptedLLM:
    """An OpenAI-compatible service that answers every item with the given tone and
    confirms all candidates; records the prompts."""

    def __init__(self, sentiment: float = 0.8, importance: int = 5) -> None:
        self.sentiment, self.importance = sentiment, importance
        self.prompts: list[tuple[str, list[dict[str, Any]]]] = []

    def complete(
        self, service: LLMService, api_key: str, system: str, user: str, schema: dict[str, Any]
    ) -> Completion:
        items = json.loads(user)
        self.prompts.append((system, items))
        answer = {
            "items": [
                {
                    "id": item["id"],
                    "summary": f"摘要 {item['title'][:10]}",
                    "sentiment": self.sentiment,
                    "event_type": "earnings",
                    "importance": self.importance,
                    "topics": [],
                    "stocks": [
                        {"symbol": c["symbol"], "sentiment": self.sentiment}
                        for c in item["candidates"]
                    ],
                }
                for item in items
            ]
        }
        return Completion(json.dumps(answer, ensure_ascii=False), 1000, 200)


class Recorder(Notifier):
    channel = "line"

    def __init__(self) -> None:
        self.sent: list[tuple[str, Severity]] = []

    def send(self, subject: str, body: str, severity: Severity = "warning") -> None:
        self.sent.append((subject, severity))


def _stock(
    engine: Engine, symbol: str, name: str, market: str = "twse", kind: str = "stock"
) -> int:
    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    "INSERT INTO stocks (symbol, market, type, name, listed_date) "
                    "VALUES (:s, :m, :t, :n, '2000-01-01') RETURNING id"
                ),
                {"s": symbol, "m": market, "t": kind, "n": name},
            ).scalar_one()
        )


def _watch(engine: Engine, *stock_ids: int) -> None:
    with engine.begin() as conn:
        for stock_id in stock_ids:
            conn.execute(text("INSERT INTO watchlist (stock_id) VALUES (:id)"), {"id": stock_id})


def _only_sources(engine: Engine, *codes: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE news_sources SET enabled = code = ANY(:codes)"), {"codes": list(codes)}
        )


def _rows(engine: Engine, sql: str, **params: Any) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql), params).all())


@pytest.fixture
def setup(clean_db: Engine, tmp_path: Path) -> Any:
    store = LocalRawStore(clean_db, tmp_path)
    router = official_router(store)
    notifier = Recorder()
    llm_client = ScriptedLLM()

    def run(name: str, now: datetime, client: Any = None, **params: Any) -> JobRunResult:
        def factory(cls: type[Job]) -> Job:
            if name == "aggregate_sentiment":
                return cls(now=lambda: now)  # type: ignore[call-arg]
            return cls(  # type: ignore[call-arg]
                now=lambda: now,
                llm=lambda engine: LLMRouter(
                    engine,
                    client or llm_client,
                    env={"GROQ_API_KEY": "k"},
                    clock=lambda: now,
                    sleep=lambda _: None,
                ),
            )

        return run_job(
            name,
            params,
            engine=clean_db,
            rawstore=store,
            notifier=notifier,
            router=router,
            job_factory=factory,
        )

    return run, notifier, llm_client


def test_requests_for_per_stock_sources() -> None:
    source = Source(
        id=1,
        code="yahoo_stock",
        name="Yahoo",
        kind="rss",
        channel="news",
        url="https://tw.stock.yahoo.com/rss?s={symbol}.{market_suffix}",
        per_stock=True,
        market=None,
        interval_minutes=30,
        keywords=[],
        use_llm=True,
        last_fetched_at=None,
    )
    requests = requests_for(source, [(1, "2330", "twse"), (2, "6488", "tpex")], frozenset())
    assert [(r.url, r.symbol) for r in requests] == [
        ("https://tw.stock.yahoo.com/rss?s=2330.TW", "2330"),
        ("https://tw.stock.yahoo.com/rss?s=6488.TWO", "6488"),
    ]


def test_announcements_are_analysed_and_alert_watched_stocks(setup: Any, clean_db: Engine) -> None:
    run, notifier, llm = setup
    longbon = _stock(clean_db, "2514", "龍邦")
    _stock(clean_db, "2072", "世紀能源")
    _stock(clean_db, "4747", "強生*", "tpex")
    _watch(clean_db, longbon)
    _only_sources(clean_db, "mops_twse", "mops_tpex")

    result = run("sync_news", ANNOUNCEMENT_DAY)
    assert result.status == "succeeded", result.error
    assert result.message is not None
    assert result.message.startswith("新增 5 則，LLM 完成 5 則，警示 1 則")
    items = _rows(
        clean_db,
        "SELECT i.external_id, i.llm_status, i.summary, i.importance, i.llm_provider, "
        "array_agg(s.symbol ORDER BY s.symbol) FILTER (WHERE s.symbol IS NOT NULL) AS symbols "
        "FROM news_items i LEFT JOIN news_item_stocks l ON l.item_id = i.id "
        "LEFT JOIN stocks s ON s.id = l.stock_id GROUP BY i.id ORDER BY i.id",
    )
    assert [i.llm_status for i in items] == ["done"] * 5
    assert all(i.llm_provider == "groq" for i in items)  # Google has no key here
    linked = {i.external_id.split("-")[0]: i.symbols for i in items}
    assert linked["2514"] == ["2514"]
    assert linked["6949"] is None  # not a listed stock in this database
    # Announcements are batched: five items in one request.
    assert len(llm.prompts) == 1
    assert len(llm.prompts[0][1]) == 5
    alert = _rows(
        clean_db,
        "SELECT kind, severity, trade_date, channels, notified_at IS NOT NULL AS sent, detail "
        "FROM alerts",
    )
    assert len(alert) == 1
    assert (alert[0].kind, alert[0].severity, alert[0].trade_date) == (
        "announcement",
        "critical",
        date(2026, 10, 21),
    )
    assert alert[0].channels == ["line"]
    assert alert[0].sent
    assert len(alert[0].detail["items"]) == 1
    assert notifier.sent == [("[重大訊息] 2514 龍邦", "critical")]
    usage = _rows(clean_db, "SELECT requests, input_tokens FROM llm_usage")
    assert usage == [(1, 1000)]

    # A rerun stores and sends nothing new (sources not due yet, items known).
    again = run("sync_news", ANNOUNCEMENT_DAY, force="true")
    assert again.message is not None
    assert again.message.startswith("新增 0 則，LLM 完成 0 則")
    assert len(notifier.sent) == 1


def test_per_stock_news_dedup_and_sentiment_alert(setup: Any, clean_db: Engine) -> None:
    run, notifier, _ = setup
    wafer = _stock(clean_db, "6488", "環球晶", "tpex")
    _watch(clean_db, wafer)
    _only_sources(clean_db, "yahoo_stock")
    result = run("sync_news", YAHOO_DAY)
    assert result.status == "succeeded", result.error
    items = _rows(
        clean_db, "SELECT llm_status, sentiment, duplicate_of FROM news_items ORDER BY id"
    )
    assert len(items) == 2
    assert [i.llm_status for i in items] == ["done", "done"]
    alerts = _rows(clean_db, "SELECT kind, severity, detail FROM alerts")
    # Only the report of the last 24 hours alerts; the older one is analysed but not sent.
    assert [(a.kind, a.severity) for a in alerts] == [("news_sentiment", "warning")]
    assert len(alerts[0].detail["items"]) == 1
    assert notifier.sent == [("[新聞警示] 6488 環球晶", "warning")]


def test_mild_news_raises_nothing(setup: Any, clean_db: Engine) -> None:
    run, notifier, _ = setup
    _watch(clean_db, _stock(clean_db, "6488", "環球晶", "tpex"))
    _only_sources(clean_db, "yahoo_stock")
    result = run("sync_news", YAHOO_DAY, client=ScriptedLLM(sentiment=0.2, importance=3))
    assert result.status == "succeeded", result.error
    assert _rows(clean_db, "SELECT count(*) FROM alerts")[0][0] == 0
    assert notifier.sent == []


def test_no_llm_keeps_items_pending_and_reports_it(setup: Any, clean_db: Engine) -> None:
    run, _, _ = setup
    _only_sources(clean_db, "ctee_stock")

    class Down:
        def complete(self, *args: Any) -> Completion:
            raise AssertionError("not called without keys")

    with clean_db.begin() as conn:
        conn.execute(text("UPDATE llm_providers SET enabled = false"))
    result = run("sync_news", YAHOO_DAY, client=Down())
    assert result.message is not None
    assert "沒有可用的 LLM 服務" in result.message
    statuses = _rows(clean_db, "SELECT llm_status FROM news_items")
    assert [s[0] for s in statuses] == ["pending", "pending"]


def test_forum_posts_use_author_tags_without_the_llm(setup: Any, clean_db: Engine) -> None:
    run, _, _ = setup
    _stock(clean_db, "00406A", "主動中信台灣收益", kind="etf")
    _only_sources(clean_db, "ptt_stock", "cmoney_forum")

    class Never:
        def complete(self, *args: Any) -> Completion:
            raise AssertionError("tagged posts need no LLM")

    result = run("sync_news", PTT_NOW, client=Never())
    assert result.status == "succeeded", result.error
    posts = _rows(
        clean_db,
        "SELECT s.code, i.llm_status, i.sentiment, i.sentiment_source, i.snippet, i.meta "
        "FROM news_items i JOIN news_sources s ON s.id = i.source_id ORDER BY s.code",
    )
    assert [(p.code, p.llm_status) for p in posts] == [
        ("cmoney_forum", "skipped"),
        ("ptt_stock", "skipped"),  # SOXS is not a Taiwan stock
    ]
    forum = posts[0]
    assert (float(forum.sentiment), forum.sentiment_source) == (0.8, "author")
    assert forum.snippet is None  # forum text is never stored
    assert forum.meta["stances"] == {"00406A": "bullish"}
    link = _rows(clean_db, "SELECT relation, weight, sentiment FROM news_item_stocks")
    assert [(r.relation, float(r.weight), float(r.sentiment)) for r in link] == [
        ("direct", 1.0, 0.8)
    ]


def test_aggregate_sentiment_and_social_retention(setup: Any, clean_db: Engine) -> None:
    run, _, _ = setup
    tsmc = _stock(clean_db, "2330", "台積電")
    with clean_db.begin() as conn:
        source = conn.execute(
            text("SELECT id FROM news_sources WHERE code = 'ctee_stock'")
        ).scalar_one()
        for external, at, tone, importance in (
            ("a", datetime(2026, 10, 22, 9, 0, tzinfo=TAIPEI), 0.6, 5),
            ("b", datetime(2026, 10, 22, 20, 0, tzinfo=TAIPEI), -0.4, 3),
        ):
            item = conn.execute(
                text(
                    "INSERT INTO news_items (source_id, channel, external_id, url, title, "
                    "published_at, sentiment, sentiment_source, importance, llm_status) "
                    "VALUES (:s, 'news', :e, 'https://x/' || :e, 't', :at, :tone, 'llm', :imp, "
                    "'done') RETURNING id"
                ),
                {"s": source, "e": external, "at": at, "tone": tone, "imp": importance},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO news_item_stocks (item_id, stock_id, relation, weight) "
                    "VALUES (:i, :s, 'direct', 1)"
                ),
                {"i": item, "s": tsmc},
            )
    result = run("aggregate_sentiment", datetime(2026, 10, 26, 6, 0, tzinfo=UTC), days="5")
    assert result.status == "succeeded", result.error
    rows = _rows(
        clean_db,
        "SELECT trade_date, scope, items, scored, sentiment, bullish, bearish FROM sentiment_daily "
        "ORDER BY trade_date, scope",
    )
    # 22 Oct 20:00 is after the close: it counts for Friday the 23rd.
    assert [(r.trade_date, r.scope, r.items, float(r.sentiment)) for r in rows] == [
        (date(2026, 10, 22), "all", 1, 0.6),
        (date(2026, 10, 22), "news", 1, 0.6),
        (date(2026, 10, 23), "all", 1, -0.4),
        (date(2026, 10, 23), "news", 1, -0.4),
    ]
    # Rerunning replaces the window instead of adding to it.
    run("aggregate_sentiment", datetime(2026, 10, 26, 6, 0, tzinfo=UTC), days="5")
    assert len(_rows(clean_db, "SELECT 1 FROM sentiment_daily")) == 4


def test_news_settings_defaults_and_overrides(clean_db: Engine) -> None:
    with clean_db.begin() as conn:
        assert NewsSettings.load(conn) == NewsSettings()
        conn.execute(
            text(
                "INSERT INTO settings (key, value) VALUES ('news', "
                '\'{"sentimentAlert": 0.6, "llmDailyItems": "x"}\')'
            )
        )
        loaded = NewsSettings.load(conn)
    assert loaded.sentiment_alert == 0.6
    assert loaded.llm_daily_items == 400  # unusable values fall back


def test_later_announcements_of_the_day_are_appended_and_sent(clean_db: Engine) -> None:
    from stockhub.etl.jobs.news_alerts import check_news_alerts

    stock = _stock(clean_db, "2514", "龍邦")
    _watch(clean_db, stock)
    with clean_db.begin() as conn:
        source = conn.execute(
            text("SELECT id FROM news_sources WHERE code = 'mops_twse'")
        ).scalar_one()
        # c was filed by another company that only names 2514 in its text.
        for external, hour, filer in (("a", 9, "2514"), ("c", 10, "2330"), ("b", 11, "2514")):
            item = conn.execute(
                text(
                    "INSERT INTO news_items (source_id, channel, external_id, url, title, "
                    "published_at, meta) VALUES (:s, 'announcement', :e, 'https://m', :t, :at, "
                    "jsonb_build_object('tags', jsonb_build_array(CAST(:filer AS text)))) "
                    "RETURNING id"
                ),
                {
                    "s": source,
                    "e": external,
                    "t": f"公告 {external}",
                    "filer": filer,
                    "at": datetime(2026, 10, 21, hour, tzinfo=TAIPEI),
                },
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO news_item_stocks (item_id, stock_id, relation, weight) "
                    "VALUES (:i, :s, 'direct', 1)"
                ),
                {"i": item, "s": stock},
            )
    notifier = Recorder()
    now = datetime(2026, 10, 21, 12, tzinfo=TAIPEI)
    assert check_news_alerts(clean_db, notifier, now) == 1
    assert len(notifier.sent) == 2
    detail = _rows(clean_db, "SELECT detail FROM alerts")[0].detail
    assert [i["title"] for i in detail["items"]] == ["公告 a", "公告 b"]
    assert check_news_alerts(clean_db, notifier, now) == 0
    assert len(notifier.sent) == 2
