"""Holding alerts (PLAN.md section 5): a held stock moving beyond its volatility threshold,
and institutional investors trading a large share of a holding's volume.

`check_holding_moves` runs after every intraday poll (poll_quotes) and once after the daily
close (check_holding_alerts in make etl-daily). It only judges today's move; one alert per
stock and day, so the 30-second polls do not repeat it. `check_institutional_flows` runs
after the chip tables are fetched (check_institutional_alerts).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import ClassVar

from sqlalchemy import Connection, text

from stockhub.common.notifier import Notifier
from stockhub.common.portfolio_store import holdings
from stockhub.common.timeutil import taipei_today, utcnow
from stockhub.engine.alerts import WINDOW, move_threshold
from stockhub.engine.chips import FLOW_SHARE, institutional_flows
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


# ----------------------------------------------------------------------------- institutional

GROUP_LABEL = {"foreign": "外資", "trust": "投信", "dealer": "自營商"}
STALE_AFTER = timedelta(days=4)
"""Institutional data older than this (a long holiday at most) is not alerted on any more."""


def latest_institutional_day(conn: Connection) -> date | None:
    day: date | None = conn.execute(
        text(
            "SELECT max(trade_date) FROM chip_coverage WHERE dataset = 'institutional' AND rows > 0"
        )
    ).scalar_one()
    return day


def check_institutional_flows(conn: Connection, notifier: Notifier, day: date) -> int:
    """Alert on each holding where an institutional group's net trade on `day` reached
    FLOW_SHARE of the volume (groups judged separately, one alert per stock and day)."""
    raised = 0
    for stock_id, shares in holdings(conn, day).items():
        row = conn.execute(
            text(
                "SELECT s.symbol, s.name, t.foreign_net, t.trust_net, t.dealer_net, "
                "p.volume, p.turnover FROM institutional_trades_daily t "
                "JOIN stocks s ON s.id = t.stock_id "
                "JOIN prices_daily p ON p.stock_id = t.stock_id AND p.trade_date = t.trade_date "
                "WHERE t.stock_id = :id AND t.trade_date = :day"
            ),
            {"id": stock_id, "day": day},
        ).first()
        if row is None:
            continue
        flows = institutional_flows(
            {"foreign": row.foreign_net, "trust": row.trust_net, "dealer": row.dealer_net},
            row.volume,
            row.turnover,
        )
        if not flows:
            continue
        parts = [
            f"{GROUP_LABEL[f.group]}{'買超' if f.net > 0 else '賣超'} {abs(f.net) / 1000:,.0f} 張"
            f"（{abs(f.share) * 100:.0f}%）"
            for f in flows
        ]
        title = f"{row.symbol} {row.name} {'、'.join(parts)}"
        detail = {
            "flows": [{"group": f.group, "net": f.net, "share": f.share} for f in flows],
            "volume": row.volume,
            "turnover": float(row.turnover),
            "threshold": FLOW_SHARE,
            "shares": shares,
        }
        alert = conn.execute(
            text(
                "INSERT INTO alerts (kind, stock_id, trade_date, severity, title, detail) "
                "VALUES ('institutional_flow', :stock_id, :day, 'warning', :title, "
                "CAST(:detail AS jsonb)) "
                "ON CONFLICT ON CONSTRAINT alerts_once_per_day DO NOTHING RETURNING id"
            ),
            {"stock_id": stock_id, "day": day, "title": title, "detail": json.dumps(detail)},
        ).first()
        if alert is None:
            continue
        raised += 1
        body = (
            f"{day} 持股 {shares:,} 股。三大法人單日買賣超占成交量（{row.volume / 1000:,.0f} 張）"
            f"達 {FLOW_SHARE * 100:.0f}% 以上：{'、'.join(parts)}。"
            f"成交金額 {float(row.turnover) / 1e8:,.1f} 億。"
        )
        try:
            notifier.send(f"[法人警示] {title}", body, "warning")
        except Exception:  # a broken notifier must not lose the recorded alert
            log.exception("could not send alert %s", alert.id)
            continue
        conn.execute(
            text("UPDATE alerts SET notified_at = :now WHERE id = :id"),
            {"now": utcnow(), "id": alert.id},
        )
    return raised


@register_job
class CheckInstitutionalAlertsJob(Job):
    name: ClassVar[str] = "check_institutional_alerts"
    description: ClassVar[str] = (
        "Alert on holdings where foreign, trust or dealer net trades reached 10% of the "
        "volume on the latest institutional day (--param date= for another day)"
    )
    uses_date: ClassVar[bool] = False

    def run(self, ctx: JobContext) -> JobOutcome:
        with ctx.engine.begin() as conn:
            latest = latest_institutional_day(conn)
            if ctx.params.get("date"):
                day = date.fromisoformat(str(ctx.params["date"]))
            elif latest is None or taipei_today() - latest > STALE_AFTER:
                return JobOutcome("skipped", f"沒有近期的三大法人資料（最新 {latest}）")
            else:
                day = latest
            raised = check_institutional_flows(conn, ctx.notifier, day)
        ctx.add_rows(raised)
        return JobOutcome(message=f"{day}：新增 {raised} 則法人警示")
