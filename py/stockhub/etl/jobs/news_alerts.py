"""News alerts for holdings and watched stocks (PLAN.md section 5, D-141).

- announcement (critical, every channel): a 重大訊息 of a watched stock. One alert row per
  stock and day; later announcements of the day are appended to detail.items and sent too.
- news_sentiment (warning, first push channel): a news item with |sentiment| and importance
  at the thresholds (settings news.sentimentAlert, news.importanceAlert); industry and theme
  relations need 0.1 more sentiment and one more importance point. The first one of a stock
  and day is sent; later ones of the day are appended without a message (the cooldown).
- social_buzz (info, site only): today's forum posts on a stock reach mean + k standard
  deviations of the previous 20 days (news.buzzSigma, at least news.buzzMinPosts).

All run after every sync_news round; reruns add nothing.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, text

from stockhub.common.notifier import Notifier, Severity
from stockhub.common.timeutil import TAIPEI, taipei_today, utcnow
from stockhub.engine.sentiment import BUZZ_HISTORY_DAYS, BUZZ_MIN_HISTORY, buzz_threshold
from stockhub.etl.jobs.news import NewsSettings
from stockhub.etl.jobs.quotes import polled_stocks

log = logging.getLogger(__name__)

LOOKBACK = timedelta(hours=24)


def check_news_alerts(engine: Engine, notifier: Notifier, now: datetime) -> int:
    """Raise the three kinds for watched stocks; returns how many alert rows are new."""
    with engine.begin() as conn:
        settings = NewsSettings.load(conn)
        watched = {
            stock_id: symbol for stock_id, symbol, _ in polled_stocks(conn, (), taipei_today(now))
        }
        if not watched:
            return 0
        names: dict[int, str] = dict(
            conn.execute(
                text("SELECT id, name FROM stocks WHERE id = ANY(:ids)"), {"ids": list(watched)}
            ).all()
        )
        label = {i: f"{watched[i]} {names.get(i, '')}".strip() for i in watched}
        raised = announcement_alerts(conn, notifier, label, now)
        raised += sentiment_alerts(conn, notifier, label, now, settings)
        raised += buzz_alerts(conn, label, now, settings)
    return raised


def _send(
    conn: Connection, notifier: Notifier, alert_id: int, subject: str, body: str, sev: Severity
) -> None:
    try:
        channels = notifier.deliver(subject, body, sev)
    except Exception:  # a broken channel must not lose the recorded alert
        log.exception("could not send alert %s", alert_id)
        return
    conn.execute(
        text(
            "UPDATE alerts SET notified_at = :now, channels = ARRAY("
            "  SELECT DISTINCT c FROM unnest(channels || CAST(:channels AS text[])) c ORDER BY c"
            ") WHERE id = :id"
        ),
        {"now": utcnow(), "channels": channels, "id": alert_id},
    )


def _taipei_day(at: datetime) -> date:
    return at.astimezone(TAIPEI).date()


def _record(
    conn: Connection,
    kind: str,
    stock_id: int,
    day: date,
    severity: Severity,
    title: str,
    entry: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> tuple[int, bool] | None:
    """Insert the day's alert, or append `entry` to it. Returns (alert id, new row), or None
    when the entry is already recorded."""
    detail = {"items": [entry], **(extra or {})}
    row = conn.execute(
        text(
            "INSERT INTO alerts (kind, stock_id, trade_date, severity, title, detail) "
            "VALUES (:kind, :stock, :day, :severity, :title, CAST(:detail AS jsonb)) "
            "ON CONFLICT ON CONSTRAINT alerts_once_per_day DO NOTHING RETURNING id"
        ),
        {
            "kind": kind,
            "stock": stock_id,
            "day": day,
            "severity": severity,
            "title": title,
            "detail": json.dumps(detail, ensure_ascii=False, default=str),
        },
    ).first()
    if row is not None:
        return int(row.id), True
    existing = conn.execute(
        text(
            "SELECT id, detail FROM alerts WHERE kind = :kind AND stock_id = :stock "
            "AND trade_date = :day"
        ),
        {"kind": kind, "stock": stock_id, "day": day},
    ).one()
    items = list((existing.detail or {}).get("items") or [])
    if any(i.get("id") == entry["id"] for i in items):
        return None
    conn.execute(
        text(
            "UPDATE alerts SET detail = jsonb_set(detail, '{items}', CAST(:items AS jsonb)) "
            "WHERE id = :id"
        ),
        {"items": json.dumps([*items, entry], ensure_ascii=False, default=str), "id": existing.id},
    )
    return int(existing.id), False


def _linked(
    conn: Connection, channel: str, stock_ids: Sequence[int], since: datetime, done_only: bool
) -> list[Any]:
    return list(
        conn.execute(
            text(
                "SELECT i.id, i.title, i.url, i.summary, i.importance, i.published_at, "
                "l.stock_id, l.relation, coalesce(l.sentiment, i.sentiment) AS sentiment, "
                "s.symbol, i.meta -> 'tags' AS tags "
                "FROM news_items i JOIN news_item_stocks l ON l.item_id = i.id "
                "JOIN stocks s ON s.id = l.stock_id "
                "WHERE i.channel = :channel AND i.duplicate_of IS NULL "
                "AND i.published_at >= :since AND l.stock_id = ANY(:ids) "
                "AND (NOT :done OR i.llm_status = 'done') "
                "ORDER BY i.published_at, i.id"
            ),
            {"channel": channel, "since": since, "ids": list(stock_ids), "done": done_only},
        ).all()
    )


def announcement_alerts(
    conn: Connection, notifier: Notifier, label: dict[int, str], now: datetime
) -> int:
    raised = 0
    for row in _linked(conn, "announcement", list(label), now - LOOKBACK, False):
        # Only the company that filed it: a parent or customer named in the text is a link
        # for the news pages, not a 重大訊息 of that stock.
        if row.relation != "direct" or row.symbol not in (row.tags or []):
            continue
        at = row.published_at.astimezone(TAIPEI)
        entry = {"id": row.id, "title": row.title, "url": row.url, "at": at.isoformat()}
        title = f"{label[row.stock_id]} 重大訊息：{row.title}"
        recorded = _record(
            conn, "announcement", row.stock_id, at.date(), "critical", title[:300], entry
        )
        if recorded is None:
            continue
        alert_id, new = recorded
        raised += int(new)
        body = "\n".join(
            part
            for part in (
                f"{at:%m/%d %H:%M} {label[row.stock_id]} 發布重大訊息",
                row.title,
                f"摘要（AI）：{row.summary}" if row.summary else None,
                row.url,
            )
            if part
        )
        _send(conn, notifier, alert_id, f"[重大訊息] {label[row.stock_id]}", body, "critical")
    return raised


def sentiment_alerts(
    conn: Connection,
    notifier: Notifier,
    label: dict[int, str],
    now: datetime,
    settings: NewsSettings,
) -> int:
    raised = 0
    for row in _linked(conn, "news", list(label), now - LOOKBACK, True):
        if row.sentiment is None or row.importance is None:
            continue
        direct = row.relation == "direct"
        tone = settings.sentiment_alert + (0 if direct else 0.1)
        importance = settings.importance_alert + (0 if direct else 1)
        if abs(float(row.sentiment)) < min(tone, 1.0) or row.importance < min(importance, 5):
            continue
        positive = float(row.sentiment) > 0
        entry = {
            "id": row.id,
            "title": row.title,
            "url": row.url,
            "sentiment": float(row.sentiment),
            "importance": row.importance,
            "relation": row.relation,
        }
        title = f"{label[row.stock_id]} 新聞{'利多' if positive else '利空'}：{row.title}"
        recorded = _record(
            conn,
            "news_sentiment",
            row.stock_id,
            _taipei_day(row.published_at),
            "warning",
            title[:300],
            entry,
        )
        if recorded is None or not recorded[1]:
            continue  # already recorded, or appended to today's alert (cooldown)
        raised += 1
        relation = {"direct": "", "industry": "（同產業）", "theme": "（同題材）"}[row.relation]
        body = "\n".join(
            part
            for part in (
                f"{label[row.stock_id]}{relation} 新聞情緒 {float(row.sentiment):+.2f}，"
                f"重要度 {row.importance}",
                row.title,
                f"摘要（AI）：{row.summary}" if row.summary else None,
                row.url,
            )
            if part
        )
        _send(conn, notifier, recorded[0], f"[新聞警示] {label[row.stock_id]}", body, "warning")
    return raised


def buzz_alerts(
    conn: Connection, label: dict[int, str], now: datetime, settings: NewsSettings
) -> int:
    today = taipei_today(now)
    first = conn.execute(
        text("SELECT min(published_at) FROM news_items WHERE channel = 'social'")
    ).scalar_one()
    if first is None or (today - _taipei_day(first)).days < BUZZ_MIN_HISTORY:
        return 0
    start = today - timedelta(days=BUZZ_HISTORY_DAYS)
    counts: dict[tuple[int, date], int] = {}
    for stock_id, day, posts in conn.execute(
        text(
            "SELECT l.stock_id, (i.published_at AT TIME ZONE 'Asia/Taipei')::date AS day, "
            "count(DISTINCT i.id) AS posts FROM news_items i "
            "JOIN news_item_stocks l ON l.item_id = i.id AND l.relation = 'direct' "
            "WHERE i.channel = 'social' AND l.stock_id = ANY(:ids) "
            "AND (i.published_at AT TIME ZONE 'Asia/Taipei')::date >= :start "
            "GROUP BY 1, 2"
        ),
        {"ids": list(label), "start": start},
    ).all():
        counts[(stock_id, day)] = int(posts)
    raised = 0
    for stock_id in label:
        posts = counts.get((stock_id, today), 0)
        history = [
            counts.get((stock_id, start + timedelta(days=d)), 0) for d in range(BUZZ_HISTORY_DAYS)
        ]
        threshold = buzz_threshold(history, settings.buzz_sigma, settings.buzz_min_posts)
        if posts < threshold:
            continue
        mean = sum(history) / len(history)
        row = conn.execute(
            text(
                "INSERT INTO alerts (kind, stock_id, trade_date, severity, title, detail) "
                "VALUES ('social_buzz', :stock, :day, 'info', :title, CAST(:detail AS jsonb)) "
                "ON CONFLICT ON CONSTRAINT alerts_once_per_day DO UPDATE SET "
                "title = EXCLUDED.title, detail = EXCLUDED.detail RETURNING (xmax = 0) AS inserted"
            ),
            {
                "stock": stock_id,
                "day": today,
                "title": (
                    f"{label[stock_id]} 社群討論暴增：今天 {posts} 篇（近 20 日平均 {mean:.1f}）"
                ),
                "detail": json.dumps(
                    {"posts": posts, "mean": round(mean, 2), "threshold": round(threshold, 2)}
                ),
            },
        ).one()
        raised += int(row.inserted)
    return raised
