"""Turnover, FIFO round-trip realized P&L, win/loss analysis, and a FIFO tax estimate.
All read the `orders` table; degrade gracefully when there are few/no closed trades."""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import pandas as pd

from core.config import cfg
from core.db import ensure_tables, get_conn
from data.universe import get_sector_map

_ORDERS = "CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY);"


def _orders(days: int | None = None) -> pd.DataFrame:
    ensure_tables(_ORDERS)
    q = "SELECT ts,ticker,side,shares,fill_price,notional FROM orders WHERE fill_price IS NOT NULL"
    params = ()
    if days:
        q += " AND ts>=?"
        params = ((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(),)
    with get_conn() as conn:
        return pd.read_sql_query(q + " ORDER BY ts", conn, params=params)


def turnover(days: int = 30, aum: float | None = None) -> dict:
    aum = aum or float(cfg.get("portfolio.aum", 1_000_000))
    df = _orders(days)
    traded = float(df["notional"].sum()) if not df.empty else 0.0
    tpct = traded / aum if aum else 0.0
    annualized = tpct * (365 / days)
    budget = float(cfg.get("reporting.turnover_budget_annual", 4.0))
    return {"days": days, "notional": round(traded, 2), "turnover": round(tpct, 4),
            "annualized": round(annualized, 2), "budget": budget,
            "vs_budget": round(annualized - budget, 2)}


def roundtrips() -> list[dict]:
    """FIFO-match opens against closes per ticker -> realized trades."""
    df = _orders()
    if df.empty:
        return []
    lots: dict[str, deque] = defaultdict(deque)   # ticker -> open lots (signed shares, px, ts)
    out = []
    for r in df.itertuples():
        signed = r.shares if r.side == "buy" else -r.shares
        q = lots[r.ticker]
        # close against opposite-sign lots first (FIFO)
        while q and (q[0][0] > 0) != (signed > 0) and abs(signed) > 1e-9:
            o_shares, o_px, o_ts = q[0]
            matched = min(abs(o_shares), abs(signed))
            long_side = o_shares > 0
            pnl = (r.fill_price - o_px) * matched * (1 if long_side else -1)
            hold = (datetime.fromisoformat(r.ts) - datetime.fromisoformat(o_ts)).days
            out.append({"ticker": r.ticker, "side": "long" if long_side else "short",
                        "shares": matched, "entry": o_px, "exit": r.fill_price,
                        "pnl": pnl, "holding_days": hold, "entry_ts": o_ts})
            o_remain = o_shares - matched * (1 if long_side else -1)
            signed += matched * (1 if long_side else -1)
            if abs(o_remain) < 1e-9:
                q.popleft()
            else:
                q[0] = (o_remain, o_px, o_ts)
        if abs(signed) > 1e-9:
            q.append((signed, r.fill_price, r.ts))
    return out


def _bucket(days: int) -> str:
    return "1-5d" if days <= 5 else "5-20d" if days <= 20 else "20-60d" if days <= 60 else "60d+"


def win_loss() -> dict:
    rt = roundtrips()
    if not rt:
        return {"n": 0, "win_rate": None, "pl_ratio": None, "by_side": {}, "by_holding": {}, "by_sector": {}}
    wins = [t["pnl"] for t in rt if t["pnl"] > 0]
    losses = [t["pnl"] for t in rt if t["pnl"] < 0]
    smap = get_sector_map()

    def agg(key):
        d = defaultdict(lambda: [0, 0])
        for t in rt:
            k = key(t)
            d[k][0 if t["pnl"] > 0 else 1] += 1
        return {k: {"wins": v[0], "losses": v[1]} for k, v in d.items()}

    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0
    return {
        "n": len(rt),
        "win_rate": round(len(wins) / len(rt), 3),
        "pl_ratio": round(avg_win / avg_loss, 2) if avg_loss else None,
        "by_side": agg(lambda t: t["side"]),
        "by_holding": agg(lambda t: _bucket(t["holding_days"])),
        "by_sector": agg(lambda t: smap.get(t["ticker"], "?")),
    }


def tax_estimate() -> dict:
    rt = roundtrips()
    st_rate = float(cfg.get("reporting.tax.short_term_rate", 0.37))
    lt_rate = float(cfg.get("reporting.tax.long_term_rate", 0.20))
    st_gain = sum(t["pnl"] for t in rt if t["holding_days"] < 365 and t["pnl"] > 0)
    lt_gain = sum(t["pnl"] for t in rt if t["holding_days"] >= 365 and t["pnl"] > 0)
    return {"short_term_gain": round(st_gain, 2), "long_term_gain": round(lt_gain, 2),
            "est_tax": round(st_gain * st_rate + lt_gain * lt_rate, 2)}
