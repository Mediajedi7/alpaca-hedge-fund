"""Order log + slippage tracking. slippage_bps is stored ADVERSE-signed (positive =
cost): buy filled above signal or sell/cover filled below signal. 30-day rolling
average / median / p95 / total $ cost, plus the worst 5 fills for the dashboard."""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone

from core.db import ensure_tables, get_conn
from core.log import get_logger

log = get_logger("costs")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, ticker TEXT, side TEXT, shares REAL,
    limit_price REAL, fill_price REAL, signal_price REAL,
    slippage_bps REAL, notional REAL, status TEXT, broker_order_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders(ts);
"""


def adverse_slippage_bps(side: str, signal: float, fill: float) -> float:
    """Positive = adverse (cost). Buy: fill>signal is bad; Sell: fill<signal is bad."""
    if not signal or fill is None:
        return 0.0
    raw = (fill - signal) / signal * 10_000
    return raw if side == "buy" else -raw


def log_order(ticker: str, side: str, shares: float, limit_price: float,
              fill_price: float | None, signal_price: float, status: str,
              broker_order_id: str | None = None) -> None:
    ensure_tables(_SCHEMA)
    slip = adverse_slippage_bps(side, signal_price, fill_price) if fill_price else None
    notional = (fill_price or limit_price) * shares
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO orders (ts,ticker,side,shares,limit_price,fill_price,signal_price,"
            "slippage_bps,notional,status,broker_order_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), ticker, side, shares, limit_price,
             fill_price, signal_price, slip, notional, status, broker_order_id))
    log.info("order %s %s %.0f sh limit=%.2f fill=%s slip=%s status=%s",
             side, ticker, shares, limit_price,
             f"{fill_price:.2f}" if fill_price else "-",
             f"{slip:.1f}bps" if slip is not None else "-", status)


def slippage_stats(days: int = 30) -> dict:
    ensure_tables(_SCHEMA)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT slippage_bps, notional FROM orders WHERE ts>=? AND fill_price IS NOT NULL "
            "AND slippage_bps IS NOT NULL", (cutoff,)).fetchall()
    bps = [r["slippage_bps"] for r in rows]
    if not bps:
        return {"n": 0, "avg_bps": 0, "median_bps": 0, "p95_bps": 0, "total_dollar_cost": 0}
    total_cost = sum(r["slippage_bps"] / 10_000 * r["notional"] for r in rows)
    p95 = sorted(bps)[min(len(bps) - 1, int(0.95 * len(bps)))]
    return {
        "n": len(bps),
        "avg_bps": round(statistics.mean(bps), 2),
        "median_bps": round(statistics.median(bps), 2),
        "p95_bps": round(p95, 2),
        "total_dollar_cost": round(total_cost, 2),
    }


def worst_fills(n: int = 5, days: int = 30) -> list[dict]:
    ensure_tables(_SCHEMA)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ts,ticker,side,slippage_bps,notional FROM orders WHERE ts>=? "
            "AND slippage_bps IS NOT NULL ORDER BY slippage_bps DESC LIMIT ?", (cutoff, n)).fetchall()
    return [dict(r) for r in rows]
