"""Read the trade ledger into the portfolio engine (twin of web/src/lib/portfolio-data.ts).

Holdings are replayed with corporate actions, previews whose ex-date has come and received
dividends, exactly as /portfolio shows them, so splits and reductions count.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Connection, text

from stockhub.engine import portfolio as pf


def _num(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def load_trades(conn: Connection) -> list[pf.Trade]:
    rows = conn.execute(
        text(
            "SELECT id, stock_id, trade_date, side, quantity, price, fee, tax, fee_rebate, "
            "day_trade FROM portfolio_transactions ORDER BY id"
        )
    ).all()
    return [
        pf.Trade(
            str(r.id),
            str(r.stock_id),
            r.trade_date.isoformat(),
            r.side,
            int(r.quantity),
            float(r.price),
            float(r.fee),
            float(r.tax),
            float(r.fee_rebate),
            bool(r.day_trade),
        )
        for r in rows
    ]


def load_events(
    conn: Connection, stock_ids: list[str], as_of: date
) -> tuple[list[pf.Action], list[pf.Preview], dict[str, pf.Receipt]]:
    if not stock_ids:
        return [], [], {}
    ids = {"ids": [int(s) for s in stock_ids]}
    actions = [
        pf.Action(
            str(r.stock_id),
            r.ex_date.isoformat(),
            r.action_type,
            _num(r.cash_dividend),
            _num(r.stock_dividend_ratio),
            _num(r.ratio),
            _num(r.prev_close),
            _num(r.reference_price),
        )
        for r in conn.execute(
            text(
                "SELECT stock_id, ex_date, action_type, cash_dividend, stock_dividend_ratio, "
                "ratio, prev_close, reference_price FROM corporate_actions "
                "WHERE stock_id = ANY(:ids) ORDER BY ex_date, id"
            ),
            ids,
        )
    ]
    previews = [
        pf.Preview(
            str(r.stock_id),
            r.ex_date.isoformat(),
            r.action_type,
            _num(r.cash_dividend),
            float(r.stock_dividend_ratio),
        )
        for r in conn.execute(
            text(
                "SELECT stock_id, ex_date, action_type, cash_dividend, stock_dividend_ratio "
                "FROM corporate_action_previews WHERE stock_id = ANY(:ids) ORDER BY ex_date"
            ),
            ids,
        )
    ]
    receipts = {
        pf.receipt_key(str(r.stock_id), r.ex_date.isoformat(), r.action_type): pf.Receipt(
            _num(r.cash), None if r.shares is None else int(r.shares)
        )
        for r in conn.execute(
            text(
                "SELECT stock_id, ex_date, action_type, cash, shares FROM dividend_receipts "
                "WHERE stock_id = ANY(:ids)"
            ),
            ids,
        )
    }
    return pf.with_previews(actions, previews, as_of.isoformat()), previews, receipts


def holdings(conn: Connection, as_of: date) -> dict[int, int]:
    """stock id -> shares held after every trade and event up to `as_of` (open only)."""
    trades = load_trades(conn)
    stock_ids = sorted({t.stock for t in trades})
    actions, _, receipts = load_events(conn, stock_ids, as_of)
    ledger = pf.replay(trades, actions, as_of=as_of.isoformat(), receipts=receipts)
    return {int(p.stock): p.shares for p in ledger.positions if p.shares > 0}
