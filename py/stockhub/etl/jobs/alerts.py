"""Holding alerts: a held stock moving beyond its volatility threshold (PLAN.md section 5).

`check_holding_moves` runs after every intraday poll (poll_quotes) and once after the daily
close (check_holding_alerts in make etl-daily). It only judges today's move; one alert per
stock and day, so the 30-second polls do not repeat it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import ClassVar

from sqlalchemy import Connection, text

from stockhub.common.notifier import Notifier
from stockhub.common.portfolio_store import holdings
from stockhub.common.timeutil import taipei_today, utcnow
from stockhub.engine.alerts import WINDOW, move_threshold
from stockhub.etl.jobs.base import Job, JobContext, JobOutcome, register_job

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Move:
    stock_id: int
    symbol: str
    name: str
    trade_date: date
    price: float
    prev_close: float
    change: float
    threshold: float
    source: str  # quote or daily


def todays_move(conn: Connection, stock_id: int, today: date) -> Move | None:
    """Today's move of one stock against the exchange reference, with its threshold from the
    adjusted closes before today. None when there is no price for today yet."""
    stock = conn.execute(
        text("SELECT symbol, name FROM stocks WHERE id = :id"), {"id": stock_id}
    ).one()
    bars = conn.execute(
        text(
            "SELECT trade_date, close, adj_factor FROM prices_daily "
            "WHERE stock_id = :id AND close IS NOT NULL AND trade_date <= :today "
            "ORDER BY trade_date DESC LIMIT :n"
        ),
        {"id": stock_id, "today": today, "n": WINDOW + 2},
    ).all()
    quote = conn.execute(
        text(
            "SELECT price, prev_close FROM quotes_latest "
            "WHERE stock_id = :id AND trade_date = :today AND price IS NOT NULL "
            "AND prev_close IS NOT NULL"
        ),
        {"id": stock_id, "today": today},
    ).first()
    if bars and bars[0].trade_date == today:
        # The close is in: it beats the last intraday snapshot.
        if len(bars) < 2:
            return None
        today_bar, history = bars[0], bars[1:]
        price = float(today_bar.close)
        prev = float(history[0].close * history[0].adj_factor / today_bar.adj_factor)
        source = "daily"
    elif quote is not None:
        history = bars
        price, prev, source = float(quote.price), float(quote.prev_close), "quote"
    else:
        return None
    if prev <= 0:
        return None
    adjusted = [float(b.close * b.adj_factor) for b in reversed(history)]
    return Move(
        stock_id,
        stock.symbol,
        stock.name,
        today,
        price,
        prev,
        price / prev - 1,
        move_threshold(adjusted),
        source,
    )


def check_holding_moves(conn: Connection, notifier: Notifier, today: date) -> int:
    """Record and send an alert for each holding whose move today reaches its threshold;
    returns how many new alerts were raised."""
    raised = 0
    for stock_id, shares in holdings(conn, today).items():
        move = todays_move(conn, stock_id, today)
        if move is None or abs(move.change) < move.threshold:
            continue
        direction = "上漲" if move.change > 0 else "下跌"
        title = f"{move.symbol} {move.name} {direction} {abs(move.change) * 100:.1f}%"
        detail = {
            "price": move.price,
            "prevClose": move.prev_close,
            "change": move.change,
            "threshold": move.threshold,
            "shares": shares,
            "source": move.source,
        }
        row = conn.execute(
            text(
                "INSERT INTO alerts (kind, stock_id, trade_date, severity, title, detail) "
                "VALUES ('holding_move', :stock_id, :day, 'warning', :title, "
                "CAST(:detail AS jsonb)) "
                "ON CONFLICT ON CONSTRAINT alerts_once_per_day DO NOTHING RETURNING id"
            ),
            {"stock_id": stock_id, "day": today, "title": title, "detail": json.dumps(detail)},
        ).first()
        if row is None:
            continue
        raised += 1
        body = (
            f"{today} 持股 {shares:,} 股，價格 {move.price:g}（參考價 {move.prev_close:g}），"
            f"變動 {move.change * 100:+.2f}%，門檻 ±{move.threshold * 100:.1f}%"
            f"（近 {WINDOW} 日報酬標準差 × 2.5，最低 3%）。"
        )
        try:
            notifier.send(f"[持股警示] {title}", body, "warning")
        except Exception:  # a broken notifier must not lose the recorded alert
            log.exception("could not send alert %s", row.id)
            continue
        conn.execute(
            text("UPDATE alerts SET notified_at = :now WHERE id = :id"),
            {"now": utcnow(), "id": row.id},
        )
    return raised


@register_job
class CheckHoldingAlertsJob(Job):
    name: ClassVar[str] = "check_holding_alerts"
    description: ClassVar[str] = "Alert on holdings moving beyond their volatility threshold today"
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        today = taipei_today()
        with ctx.engine.begin() as conn:
            raised = check_holding_moves(conn, ctx.notifier, today)
        ctx.add_rows(raised)
        return JobOutcome(message=f"{today}：新增 {raised} 則持股警示")
