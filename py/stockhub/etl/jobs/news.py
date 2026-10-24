"""News, announcements and social posts (M6): fetch, link to stocks, fold duplicates, LLM.

One round (sync_news) fetches every enabled source that is due (news_sources.
interval_minutes; force=true fetches all), stores new items with their stock links, folds
repeated news of one event into its first report (D-139), sends pending items to the LLM in
batches (free services first, D-137) and raises alerts. poll_news repeats rounds from 07:00
to 23:00 Taipei (make etl-news).

The funnel (PLAN.md section 5): items of sources with use_llm off, forum posts that concern
no Taiwan stock and posts whose author tagged every stock 看多/看空 are not sent; the rest
go in priority order (watched stocks, announcements, linked news, posts, the rest) up to
the daily item cap (settings news.llmDailyItems). Items still pending after STALE_AFTER are
skipped. Text for the LLM is re-read from RawStore when an item waits for a later round,
since bodies are never stored (D-138).

aggregate_sentiment rebuilds sentiment_daily for recent days and deletes forum raw objects
older than SOCIAL_RAW_DAYS.
"""

from __future__ import annotations

import json
import logging
import time as time_module
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, ClassVar

from sqlalchemy import Connection, Engine, text

from stockhub.common.llm import (
    LLMRouter,
    LLMService,
    NoLLMServiceError,
    check_service,
)
from stockhub.common.rawstore import RawStore
from stockhub.common.settings import environment
from stockhub.common.timeutil import TAIPEI, taipei_today, utcnow
from stockhub.common.trading_calendar import trading_days_between
from stockhub.engine.news import (
    STRONG,
    StockMatcher,
    find_duplicate,
    related_links,
)
from stockhub.engine.sentiment import LinkedItem, aggregate, author_sentiment
from stockhub.etl.jobs.base import Job, JobContext, JobOutcome, register_job
from stockhub.etl.jobs.quotes import polled_stocks
from stockhub.etl.news_analysis import (
    BATCH_SIZE,
    BatchAnalysis,
    ItemAnalysis,
    PromptItem,
    accept,
    system_prompt,
    user_prompt,
)
from stockhub.etl.providers.base import NewsItem, NewsProvider, NewsRequest, RawResponse
from stockhub.etl.providers.router import ProviderRouter

log = logging.getLogger(__name__)

KNOWN_DAYS = 4
"""External ids of this many days are passed to sources that read item pages one by one."""
STALE_AFTER = timedelta(days=3)
MAX_ATTEMPTS = 3
MATCH_TEXT_CHARS = 3000
SOCIAL_RAW_DAYS = 30
SOCIAL_PROVIDERS = ("ptt", "cmoney")
DEFAULT_START = time(7, 0)
DEFAULT_UNTIL = time(23, 0)
DEFAULT_INTERVAL = 60.0


@dataclass(frozen=True)
class NewsSettings:
    """settings key 'news' (camelCase JSON, edited on /admin)."""

    llm_daily_items: int = 400
    llm_daily_usd_cap: float = 0.0
    sentiment_alert: float = 0.7
    importance_alert: int = 4
    buzz_sigma: float = 3.0
    buzz_min_posts: int = 5

    @classmethod
    def load(cls, conn: Connection) -> NewsSettings:
        value = conn.execute(
            text("SELECT value FROM settings WHERE key = 'news'")
        ).scalar_one_or_none()
        data: dict[str, Any] = value if isinstance(value, dict) else {}
        defaults = cls()
        keys = {
            "llm_daily_items": "llmDailyItems",
            "llm_daily_usd_cap": "llmDailyUsdCap",
            "sentiment_alert": "sentimentAlert",
            "importance_alert": "importanceAlert",
            "buzz_sigma": "buzzSigma",
            "buzz_min_posts": "buzzMinPosts",
        }
        values: dict[str, Any] = {}
        for attr, key in keys.items():
            default = getattr(defaults, attr)
            try:
                values[attr] = type(default)(data.get(key, default))
            except (TypeError, ValueError):
                values[attr] = default
        return cls(**values)


@dataclass(frozen=True)
class Source:
    id: int
    code: str
    name: str
    kind: str
    channel: str
    url: str | None
    per_stock: bool
    market: str | None
    interval_minutes: int
    keywords: list[str]
    use_llm: bool
    last_fetched_at: datetime | None

    def due(self, now: datetime) -> bool:
        return self.last_fetched_at is None or now - self.last_fetched_at >= timedelta(
            minutes=self.interval_minutes
        )


def load_sources(conn: Connection, codes: Iterable[str] | None = None) -> list[Source]:
    rows = conn.execute(
        text(
            "SELECT id, code, name, kind, channel, url, per_stock, market, interval_minutes, "
            "keywords, use_llm, last_fetched_at FROM news_sources WHERE enabled "
            "AND (CAST(:codes AS text[]) IS NULL OR code = ANY(:codes)) ORDER BY id"
        ),
        {"codes": list(codes) if codes is not None else None},
    ).all()
    return [Source(**{**r._mapping, "keywords": list(r.keywords or [])}) for r in rows]


def requests_for(
    source: Source, watched: Sequence[tuple[int, str, str]], known: frozenset[str]
) -> list[NewsRequest]:
    base = {"source": source.code, "kind": source.kind, "known": known}
    if not source.per_stock:
        return [NewsRequest(url=source.url, market=source.market, **base)]  # type: ignore[arg-type]
    out = []
    for _, symbol, market in watched:
        url = (source.url or "").format(
            symbol=symbol, market_suffix="TWO" if market == "tpex" else "TW"
        )
        out.append(NewsRequest(url=url, symbol=symbol, **base))  # type: ignore[arg-type]
    return out


# ----------------------------------------------------------------------------- context


@dataclass
class Lookup:
    """What linking needs, read once per round."""

    matcher: StockMatcher
    symbols: dict[int, tuple[str, str]]
    """stock_id -> (symbol, name)."""
    watched: Sequence[tuple[int, str, str]]
    watched_industries: dict[int, str]
    theme_members: dict[str, list[int]]
    recent_news: list[tuple[int, str, str, float, frozenset[int]]] = field(default_factory=list)

    @classmethod
    def load(cls, conn: Connection, today: date, now: datetime) -> Lookup:
        stocks = conn.execute(
            text("SELECT id, symbol, name, industry FROM stocks WHERE delisted_date IS NULL")
        ).all()
        aliases: dict[str, int] = dict(
            conn.execute(text("SELECT alias, stock_id FROM stock_aliases")).all()
        )
        watched = polled_stocks(conn, (), today)
        industries = {r.id: r.industry for r in stocks if r.industry}
        themes: dict[str, list[int]] = {}
        for name, stock_id in conn.execute(
            text(
                "SELECT t.name, st.stock_id FROM themes t JOIN stock_themes st "
                "ON st.theme_id = t.id WHERE st.valid_from <= :d "
                "AND (st.valid_to IS NULL OR st.valid_to >= :d)"
            ),
            {"d": today},
        ).all():
            themes.setdefault(name, []).append(stock_id)
        lookup = cls(
            matcher=StockMatcher({r.symbol: (r.id, r.name) for r in stocks}, aliases),
            symbols={r.id: (r.symbol, r.name) for r in stocks},
            watched=watched,
            watched_industries={i: industries[i] for i, _, _ in watched if i in industries},
            theme_members=themes,
        )
        since = now - timedelta(hours=48)
        for row in conn.execute(
            text(
                "SELECT i.id, i.url, i.title, i.published_at, "
                "coalesce(array_agg(l.stock_id) FILTER (WHERE l.relation = 'direct'), "
                "'{}'::bigint[]) AS stocks FROM news_items i "
                "LEFT JOIN news_item_stocks l ON l.item_id = i.id "
                "WHERE i.channel = 'news' AND i.duplicate_of IS NULL "
                "AND i.published_at >= :since GROUP BY i.id"
            ),
            {"since": since},
        ).all():
            lookup.recent_news.append(
                (row.id, row.url, row.title, _hours(row.published_at), frozenset(row.stocks))
            )
        return lookup


def _hours(at: datetime) -> float:
    return at.timestamp() / 3600


# ----------------------------------------------------------------------------- storing


def store_items(
    conn: Connection,
    source: Source,
    items: list[NewsItem],
    raw_object_id: int | None,
    lookup: Lookup,
    bodies: dict[int, str],
) -> int:
    """Insert new items with their links and funnel status; refresh meta of known ones.
    Returns how many were new. Bodies of new items are kept in `bodies` for this round."""
    new = 0
    for item in items:
        if source.keywords and not any(k in item.title for k in source.keywords):
            continue
        meta = {**item.meta, "tags": item.symbols}
        if item.stances:
            meta["stances"] = item.stances
        row = conn.execute(
            text(
                "INSERT INTO news_items (source_id, channel, external_id, url, title, snippet, "
                "published_at, meta, raw_object_id) VALUES (:source, :channel, :external, :url, "
                ":title, :snippet, :published, CAST(:meta AS jsonb), :raw) "
                "ON CONFLICT ON CONSTRAINT news_items_natural_key DO UPDATE SET "
                "meta = news_items.meta || EXCLUDED.meta "
                "RETURNING id, (xmax = 0) AS inserted"
            ),
            {
                "source": source.id,
                "channel": source.channel,
                "external": item.external_id,
                "url": item.url,
                "title": item.title,
                "snippet": item.snippet,
                "published": item.published_at,
                "meta": json.dumps(meta, ensure_ascii=False, default=str),
                "raw": raw_object_id,
            },
        ).one()
        if not row.inserted:
            continue
        new += 1
        item_id = int(row.id)
        if item.body:
            bodies[item_id] = item.body
        found = lookup.matcher.find(
            f"{item.title}\n{item.snippet or ''}\n{(item.body or '')[:MATCH_TEXT_CHARS]}",
            item.symbols,
        )
        # Weak matches (two-character names in the text) need the LLM's confirmation; the
        # title of a post ([標的] 2059川湖) and the source's own tags are trusted as they are.
        strong = {k for k, v in found.items() if v in STRONG}
        strong |= set(lookup.matcher.find(item.title, item.symbols))
        stance_of = _stances(item, lookup)
        status, duplicate, sentiment = _funnel(
            source, item, item_id, found, strong, stance_of, lookup
        )
        for stock_id in found if status == "pending" else strong:
            conn.execute(
                text(
                    "INSERT INTO news_item_stocks (item_id, stock_id, relation, weight, sentiment) "
                    "VALUES (:item, :stock, 'direct', 1, :s) ON CONFLICT DO NOTHING"
                ),
                {"item": item_id, "stock": stock_id, "s": author_sentiment(stance_of(stock_id))},
            )
        conn.execute(
            text(
                "UPDATE news_items SET llm_status = :status, duplicate_of = :dup, "
                "sentiment = :s, sentiment_source = CASE WHEN CAST(:s AS numeric) IS NULL "
                "THEN NULL ELSE 'author' END WHERE id = :id"
            ),
            {"status": status, "dup": duplicate, "s": sentiment, "id": item_id},
        )
    return new


def _stances(item: NewsItem, lookup: Lookup) -> Callable[[int], str | None]:
    """Author stance per stock: forum tags per symbol, or a PTT post's 分類 for all."""
    whole = item.meta.get("stance")

    def stance(stock_id: int) -> str | None:
        symbol = lookup.symbols.get(stock_id, ("", ""))[0]
        return item.stances.get(symbol) or whole

    return stance


def _funnel(
    source: Source,
    item: NewsItem,
    item_id: int,
    found: dict[int, str],
    strong: set[int],
    stance_of: Callable[[int], str | None],
    lookup: Lookup,
) -> tuple[str, int | None, float | None]:
    """(llm_status, duplicate_of, author sentiment) of a new item."""
    if source.channel == "social":
        if not found:
            return "skipped", None, None
        tones = [author_sentiment(stance_of(s)) for s in found]
        if strong and all(t is not None for t in tones):
            known = [t for t in tones if t is not None]
            return "skipped", None, round(sum(known) / len(known), 3)
        return ("pending" if source.use_llm else "skipped"), None, None
    if source.channel == "news":
        stocks = frozenset(found)
        duplicate = find_duplicate(
            item.url, item.title, _hours(item.published_at), stocks, lookup.recent_news
        )
        if duplicate is not None:
            return "duplicate", duplicate, None
        lookup.recent_news.append(
            (item_id, item.url, item.title, _hours(item.published_at), stocks)
        )
    return ("pending" if source.use_llm else "skipped"), None, None


# ----------------------------------------------------------------------------- fetching


@dataclass
class RoundReport:
    new_items: int = 0
    analysed: int = 0
    failed_items: int = 0
    alerts: int = 0
    source_errors: list[str] = field(default_factory=list)
    llm_note: str | None = None

    def message(self) -> str:
        parts = [f"新增 {self.new_items} 則", f"LLM 完成 {self.analysed} 則"]
        if self.failed_items:
            parts.append(f"LLM 放棄 {self.failed_items} 則")
        if self.alerts:
            parts.append(f"警示 {self.alerts} 則")
        if self.llm_note:
            parts.append(self.llm_note)
        if self.source_errors:
            parts.append("來源失敗：" + "；".join(self.source_errors))
        return "，".join(parts)


def fetch_sources(
    engine: Engine,
    router: ProviderRouter,
    lookup: Lookup,
    now: datetime,
    report: RoundReport,
    bodies: dict[int, str],
    force: bool = False,
    codes: Iterable[str] | None = None,
) -> None:
    with engine.connect() as conn:
        sources = load_sources(conn, codes)
    for source in sources:
        if not (force or source.due(now)):
            continue
        with engine.connect() as conn:
            known = frozenset(
                conn.execute(
                    text(
                        "SELECT external_id FROM news_items WHERE source_id = :s "
                        "AND fetched_at >= :since"
                    ),
                    {"s": source.id, "since": now - timedelta(days=KNOWN_DAYS)},
                ).scalars()
            )
        errors = []
        for request in requests_for(source, lookup.watched, known):
            try:
                fetched = router.news(request)
            except Exception as exc:
                errors.append(f"{request.symbol or ''}{type(exc).__name__}: {exc}"[:300])
                continue
            with engine.begin() as conn:
                report.new_items += store_items(
                    conn, source, fetched.items, fetched.raw.id, lookup, bodies
                )
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE news_sources SET last_fetched_at = :now, "
                    "last_success_at = CASE WHEN :ok THEN :now ELSE last_success_at END, "
                    "last_error = :error WHERE id = :id"
                ),
                {
                    "now": now,
                    "ok": not errors,
                    "error": "；".join(errors)[:1000] if errors else None,
                    "id": source.id,
                },
            )
        if errors:
            report.source_errors.append(f"{source.name}（{len(errors)}）")


# ----------------------------------------------------------------------------- analysis


@dataclass(frozen=True)
class Pending:
    id: int
    channel: str
    source: str
    title: str
    snippet: str | None
    external_id: str
    raw_object_id: int | None
    attempts: int


def pending_items(conn: Connection, watched: list[int], now: datetime, limit: int) -> list[Pending]:
    """Pending items in funnel order; items pending longer than STALE_AFTER are skipped."""
    conn.execute(
        text(
            "UPDATE news_items SET llm_status = 'skipped' "
            "WHERE llm_status = 'pending' AND published_at < :cutoff"
        ),
        {"cutoff": now - STALE_AFTER},
    )
    rows = conn.execute(
        text(
            "SELECT i.id, i.channel, s.name AS source, i.title, i.snippet, i.external_id, "
            "i.raw_object_id, i.llm_attempts AS attempts, "
            "EXISTS (SELECT 1 FROM news_item_stocks l WHERE l.item_id = i.id "
            "        AND l.stock_id = ANY(:watched)) AS watched, "
            "EXISTS (SELECT 1 FROM news_item_stocks l WHERE l.item_id = i.id) AS linked "
            "FROM news_items i JOIN news_sources s ON s.id = i.source_id "
            "WHERE i.llm_status = 'pending' "
            "ORDER BY watched DESC, (i.channel = 'announcement') DESC, linked DESC, "
            "(i.channel = 'news') DESC, i.published_at DESC LIMIT :n"
        ),
        {"watched": watched, "n": limit},
    ).all()
    return [
        Pending(
            r.id,
            r.channel,
            r.source,
            r.title,
            r.snippet,
            r.external_id,
            r.raw_object_id,
            r.attempts,
        )
        for r in rows
    ]


def reread_bodies(
    engine: Engine, rawstore: RawStore, router: ProviderRouter, items: list[Pending]
) -> dict[int, str]:
    """Bodies of items from earlier rounds, parsed again from their raw objects."""
    wanted: dict[int, list[Pending]] = {}
    for item in items:
        if item.raw_object_id is not None:
            wanted.setdefault(item.raw_object_id, []).append(item)
    if not wanted:
        return {}
    try:
        providers = {p.name: p for p in router.registry.providers_for("news")}
    except Exception:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, provider, dataset, params, uri FROM raw_objects WHERE id = ANY(:ids)"),
            {"ids": list(wanted)},
        ).all()
    out: dict[int, str] = {}
    for row in rows:
        provider = providers.get(row.provider)
        if not isinstance(provider, NewsProvider):
            continue
        try:
            parsed = provider.parse_news(
                RawResponse(row.dataset, rawstore.get(row.uri), dict(row.params))
            )
        except Exception:
            log.exception("could not re-read raw object %s", row.id)
            continue
        by_external = {p.external_id: p.body for p in parsed if p.body}
        for item in wanted[row.id]:
            body = by_external.get(item.external_id)
            if body:
                out[item.id] = body
    return out


def _candidates(conn: Connection, item_ids: list[int]) -> dict[int, list[tuple[str, str]]]:
    out: dict[int, list[tuple[str, str]]] = {}
    for item_id, symbol, name in conn.execute(
        text(
            "SELECT l.item_id, s.symbol, s.name FROM news_item_stocks l "
            "JOIN stocks s ON s.id = l.stock_id WHERE l.item_id = ANY(:ids) "
            "AND l.relation = 'direct' ORDER BY l.item_id, s.symbol"
        ),
        {"ids": item_ids},
    ).all():
        out.setdefault(item_id, []).append((symbol, name))
    return out


def analyse_pending(
    engine: Engine,
    rawstore: RawStore,
    router: ProviderRouter,
    llm: LLMRouter,
    lookup: Lookup,
    now: datetime,
    report: RoundReport,
    bodies: dict[int, str],
) -> None:
    with engine.begin() as conn:
        settings = NewsSettings.load(conn)
        start = datetime.combine(taipei_today(now), time(), TAIPEI)
        done_today = conn.execute(
            text(
                "SELECT count(*) FROM news_items WHERE processed_at >= :start "
                "AND llm_provider IS NOT NULL"
            ),
            {"start": start},
        ).scalar_one()
        room = settings.llm_daily_items - int(done_today)
        if room <= 0:
            report.llm_note = f"已達每日 LLM 上限 {settings.llm_daily_items} 則"
            return
        items = pending_items(conn, [w[0] for w in lookup.watched], now, room)
        slang = [
            (r.term, r.meaning)
            for r in conn.execute(text("SELECT term, meaning FROM slang_terms ORDER BY term"))
        ]
    if not items:
        return
    missing = [i for i in items if i.id not in bodies]
    bodies = {**bodies, **reread_bodies(engine, rawstore, router, missing)}
    with engine.connect() as conn:
        candidates = _candidates(conn, [i.id for i in items])
    for social in (False, True):
        group = [i for i in items if (i.channel == "social") == social]
        system = system_prompt(social, slang)
        for start_at in range(0, len(group), BATCH_SIZE):
            batch = group[start_at : start_at + BATCH_SIZE]
            prompt_items = [
                PromptItem(
                    id=str(i.id),
                    channel=i.channel,  # type: ignore[arg-type]
                    source=i.source,
                    title=i.title,
                    text=bodies.get(i.id) or i.snippet or "",
                    candidates=candidates.get(i.id, []),
                )
                for i in batch
            ]
            try:
                answer = llm.ask(system, user_prompt(prompt_items), BatchAnalysis)
            except NoLLMServiceError as exc:
                if str(exc).startswith("no LLM service available"):
                    report.llm_note = "沒有可用的 LLM 服務（金鑰、額度或冷卻中）"
                    return
                with engine.begin() as conn:
                    report.failed_items += _count_attempt(conn, [i.id for i in batch])
                continue
            accepted = accept(answer.value, prompt_items)
            with engine.begin() as conn:
                for item in batch:
                    result = accepted.get(str(item.id))
                    if result is None:
                        report.failed_items += _count_attempt(conn, [item.id])
                        continue
                    apply_analysis(conn, item.id, result, answer.service, now, lookup)
                    report.analysed += 1


def _count_attempt(conn: Connection, item_ids: list[int]) -> int:
    """One more failed attempt; items that reach MAX_ATTEMPTS fail for good."""
    rows = conn.execute(
        text(
            "UPDATE news_items SET llm_attempts = llm_attempts + 1, "
            "llm_status = CASE WHEN llm_attempts + 1 >= :max THEN 'failed' ELSE llm_status END "
            "WHERE id = ANY(:ids) RETURNING llm_status"
        ),
        {"ids": item_ids, "max": MAX_ATTEMPTS},
    ).scalars()
    return sum(1 for status in rows if status == "failed")


def apply_analysis(
    conn: Connection,
    item_id: int,
    result: ItemAnalysis,
    service: LLMService,
    now: datetime,
    lookup: Lookup,
) -> None:
    conn.execute(
        text(
            "UPDATE news_items SET summary = :summary, sentiment = :sentiment, "
            "sentiment_source = 'llm', event_type = :event, importance = :importance, "
            "topics = :topics, llm_provider = :provider, llm_model = :model, "
            "processed_at = :now, llm_status = 'done', llm_attempts = llm_attempts + 1 "
            "WHERE id = :id"
        ),
        {
            "summary": result.summary,
            "sentiment": round(result.sentiment, 3),
            "event": result.event_type,
            "importance": result.importance,
            "topics": result.topics,
            "provider": service.code,
            "model": service.model,
            "now": now,
            "id": item_id,
        },
    )
    tags = set(
        conn.execute(
            text("SELECT meta -> 'tags' FROM news_items WHERE id = :id"), {"id": item_id}
        ).scalar_one()
        or []
    )
    confirmed = {s.symbol: s.sentiment for s in result.stocks}
    direct: set[int] = set()
    for stock_id, symbol, tone in conn.execute(
        text(
            "SELECT l.stock_id, s.symbol, l.sentiment FROM news_item_stocks l "
            "JOIN stocks s ON s.id = l.stock_id WHERE l.item_id = :id AND l.relation = 'direct'"
        ),
        {"id": item_id},
    ).all():
        if symbol in confirmed:
            direct.add(stock_id)
            if tone is None:  # an author's own tag is kept
                conn.execute(
                    text(
                        "UPDATE news_item_stocks SET sentiment = :s "
                        "WHERE item_id = :id AND stock_id = :stock"
                    ),
                    {"s": round(confirmed[symbol], 3), "id": item_id, "stock": stock_id},
                )
        elif symbol in tags:
            direct.add(stock_id)  # the source named it: keep even if the model did not
        else:
            conn.execute(
                text("DELETE FROM news_item_stocks WHERE item_id = :id AND stock_id = :stock"),
                {"id": item_id, "stock": stock_id},
            )
    related = related_links(result.topics, direct, lookup.watched_industries, lookup.theme_members)
    for stock_id, (relation, weight) in related.items():
        conn.execute(
            text(
                "INSERT INTO news_item_stocks (item_id, stock_id, relation, weight) "
                "VALUES (:item, :stock, :relation, :weight) ON CONFLICT DO NOTHING"
            ),
            {"item": item_id, "stock": stock_id, "relation": relation, "weight": weight},
        )


# ----------------------------------------------------------------------------- jobs

AlertCheck = Callable[[Engine, Any, datetime], int]


def _no_alerts(engine: Engine, notifier: Any, now: datetime) -> int:
    return 0


def run_round(
    ctx: JobContext,
    now: datetime,
    llm: LLMRouter,
    alerts: AlertCheck,
    force: bool = False,
    codes: Iterable[str] | None = None,
) -> RoundReport:
    router = ctx.require_router()
    report = RoundReport()
    bodies: dict[int, str] = {}
    with ctx.engine.connect() as conn:
        lookup = Lookup.load(conn, taipei_today(now), now)
    fetch_sources(ctx.engine, router, lookup, now, report, bodies, force, codes)
    analyse_pending(ctx.engine, ctx.rawstore, router, llm, lookup, now, report, bodies)
    report.alerts = alerts(ctx.engine, ctx.notifier, now)
    ctx.add_rows(report.new_items + report.analysed)
    return report


def _flag(value: object) -> bool:
    return str(value or "").lower() in {"1", "true", "yes"}


@register_job
class SyncNewsJob(Job):
    name: ClassVar[str] = "sync_news"
    description: ClassVar[str] = (
        "One round of news, announcements and forum posts: fetch due sources, link, LLM, "
        "alerts (params: force=true fetches every source, sources=code,code)"
    )
    uses_date: ClassVar[bool] = False
    timeout: ClassVar[timedelta] = timedelta(minutes=30)

    def __init__(
        self,
        now: Callable[[], datetime] = utcnow,
        llm: Callable[[Engine], LLMRouter] | None = None,
        alerts: AlertCheck | None = None,
    ) -> None:
        self.now = now
        self.llm = llm or (lambda engine: LLMRouter(engine, env=environment()))
        self.alerts = alerts

    def run(self, ctx: JobContext) -> JobOutcome:
        codes = [c.strip() for c in str(ctx.params.get("sources") or "").split(",") if c.strip()]
        report = run_round(
            ctx,
            self.now(),
            self.llm(ctx.engine),
            self.alerts or _default_alerts(),
            force=_flag(ctx.params.get("force")),
            codes=codes or None,
        )
        return JobOutcome(message=report.message())


@register_job
class PollNewsJob(Job):
    name: ClassVar[str] = "poll_news"
    description: ClassVar[str] = (
        "Rounds of sync_news from 07:00 to 23:00 Taipei (params: interval seconds, until HH:MM)"
    )
    uses_date: ClassVar[bool] = False
    timeout: ClassVar[timedelta] = timedelta(hours=17)

    def __init__(
        self,
        now: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], None] = time_module.sleep,
        llm: Callable[[Engine], LLMRouter] | None = None,
        alerts: AlertCheck | None = None,
    ) -> None:
        self.now, self.sleep = now, sleep
        self.llm = llm or (lambda engine: LLMRouter(engine, env=environment()))
        self.alerts = alerts

    def run(self, ctx: JobContext) -> JobOutcome:
        interval = float(ctx.params.get("interval") or DEFAULT_INTERVAL)
        until = _clock(ctx.params.get("until"), DEFAULT_UNTIL)
        llm = self.llm(ctx.engine)
        alerts = self.alerts or _default_alerts()
        rounds, total = 0, RoundReport()
        while True:
            now = self.now()
            local = now.astimezone(TAIPEI)
            if local.time() >= until:
                break
            if local.time() < DEFAULT_START:
                start = datetime.combine(local.date(), DEFAULT_START, TAIPEI)
                self.sleep(min(interval, (start - local).total_seconds()))
                continue
            try:
                report = run_round(ctx, now, llm, alerts)
            except Exception:  # one bad round must not end the day's polling
                log.exception("news round failed")
                self.sleep(interval)
                continue
            rounds += 1
            total.new_items += report.new_items
            total.analysed += report.analysed
            total.failed_items += report.failed_items
            total.alerts += report.alerts
            self.sleep(interval)
        if not rounds:
            return JobOutcome("skipped", f"{until:%H:%M} 之後不輪詢")
        return JobOutcome(message=f"{rounds} 輪：{total.message()}")


def _clock(value: object, default: time) -> time:
    if not value:
        return default
    hour, _, minute = str(value).partition(":")
    return time(int(hour), int(minute or 0))


def _default_alerts() -> AlertCheck:
    from stockhub.etl.jobs.news_alerts import check_news_alerts

    return check_news_alerts


# ----------------------------------------------------------------------------- sentiment


def rebuild_sentiment(conn: Connection, start: date, end: date, today: date) -> int:
    """Recompute sentiment_daily for trading days in [start, end]; returns rows written."""
    days = trading_days_between(conn, start - timedelta(days=10), end)
    window = [d for d in days if start <= d <= end]
    if not window:
        return 0
    # Items published after the previous session's close count for the first day.
    before = [d for d in days if d < window[0]]
    since = (
        datetime.combine(before[-1], time(13, 30), TAIPEI)
        if before
        else datetime.combine(window[0], time(), TAIPEI) - timedelta(days=7)
    )
    until = datetime.combine(window[-1], time(13, 30), TAIPEI)
    rows = conn.execute(
        text(
            "SELECT l.stock_id, i.published_at, i.channel, s.code AS source, l.weight, "
            "coalesce(l.sentiment, i.sentiment) AS sentiment, i.importance, "
            "coalesce((i.meta ->> 'pushes')::int, 0) AS pushes, "
            "coalesce((i.meta ->> 'boos')::int, 0) AS boos "
            "FROM news_items i JOIN news_item_stocks l ON l.item_id = i.id "
            "JOIN news_sources s ON s.id = i.source_id "
            "WHERE i.duplicate_of IS NULL AND i.published_at > :since "
            "AND i.published_at <= :until"
        ),
        {"since": since, "until": until},
    ).all()
    items = [
        LinkedItem(
            stock_id=r.stock_id,
            published_at=r.published_at,
            scope=r.source if r.channel == "social" else r.channel,
            weight=float(r.weight),
            sentiment=float(r.sentiment) if r.sentiment is not None else None,
            importance=r.importance,
            pushes=r.pushes,
            boos=r.boos,
        )
        for r in rows
    ]
    figures = aggregate(items, window)
    conn.execute(
        text("DELETE FROM sentiment_daily WHERE trade_date BETWEEN :s AND :e"),
        {"s": window[0], "e": window[-1]},
    )
    for f in figures.values():
        conn.execute(
            text(
                "INSERT INTO sentiment_daily (stock_id, trade_date, scope, items, scored, "
                "sentiment, bullish, bearish, pushes, boos) VALUES (:stock, :day, :scope, "
                ":items, :scored, :sentiment, :bullish, :bearish, :pushes, :boos)"
            ),
            {
                "stock": f.stock_id,
                "day": f.trade_date,
                "scope": f.scope,
                "items": f.items,
                "scored": f.scored,
                "sentiment": f.sentiment,
                "bullish": f.bullish,
                "bearish": f.bearish,
                "pushes": f.pushes,
                "boos": f.boos,
            },
        )
    return len(figures)


def purge_social_raw(engine: Engine, rawstore: RawStore, now: datetime) -> int:
    with engine.connect() as conn:
        ids = (
            conn.execute(
                text(
                    "SELECT id FROM raw_objects WHERE provider = ANY(:providers) "
                    "AND dataset = 'posts' AND fetched_at < :cutoff"
                ),
                {
                    "providers": list(SOCIAL_PROVIDERS),
                    "cutoff": now - timedelta(days=SOCIAL_RAW_DAYS),
                },
            )
            .scalars()
            .all()
        )
    return sum(1 for raw_id in ids if rawstore.delete(int(raw_id)))


@register_job
class AggregateSentimentJob(Job):
    name: ClassVar[str] = "aggregate_sentiment"
    description: ClassVar[str] = (
        "Rebuild sentiment_daily for recent trading days (params: days=5, or start= end=) and "
        "delete forum raw objects older than 30 days"
    )
    uses_date: ClassVar[bool] = False

    def __init__(self, now: Callable[[], datetime] = utcnow) -> None:
        self.now = now

    def run(self, ctx: JobContext) -> JobOutcome:
        now = self.now()
        today = taipei_today(now)
        if ctx.params.get("start"):
            start = date.fromisoformat(str(ctx.params["start"]))
            end = date.fromisoformat(str(ctx.params.get("end") or today.isoformat()))
        else:
            start = today - timedelta(days=int(ctx.params.get("days") or 5))
            end = today
        with ctx.engine.begin() as conn:
            rows = rebuild_sentiment(conn, start, end, today)
        purged = purge_social_raw(ctx.engine, ctx.rawstore, now)
        ctx.add_rows(rows)
        return JobOutcome(
            message=f"{start}～{end}：情緒 {rows} 列；刪除 {purged} 個超過 30 天的論壇原始檔"
        )


@register_job
class CheckLlmProvidersJob(Job):
    name: ClassVar[str] = "check_llm_providers"
    description: ClassVar[str] = (
        "Check every enabled LLM service: key present and model listed (GET /models)"
    )
    uses_date: ClassVar[bool] = False

    def __init__(self, env: Callable[[], dict[str, str]] = environment, client: Any = None) -> None:
        self.env, self.client = env, client

    def run(self, ctx: JobContext) -> JobOutcome:
        env = self.env()
        router = LLMRouter(ctx.engine, env=env)
        lines = []
        for service in router.services():
            key = (env.get(service.api_key_env) or "").strip()
            if not key:
                ok, message = False, f"沒有設定 {service.api_key_env}"
            else:
                ok, message = check_service(service, key, self.client)
            with ctx.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE llm_providers SET last_error = :e, "
                        "last_error_at = CASE WHEN :ok THEN last_error_at ELSE :now END, "
                        "cooldown_until = CASE WHEN :ok THEN NULL ELSE cooldown_until END "
                        "WHERE id = :id"
                    ),
                    {"e": None if ok else message, "ok": ok, "now": utcnow(), "id": service.id},
                )
            lines.append(f"{service.name}：{message}")
        return JobOutcome(message="；".join(lines) or "沒有啟用的 LLM 服務")
