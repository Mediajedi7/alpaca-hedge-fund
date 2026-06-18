"""JARVIS — the fund's AI persona. Builds a system-state snapshot (cached as Claude
context), answers chat questions, and authors the daily investors letter + weekly commentary."""
from __future__ import annotations

import json
from datetime import date, datetime

from analysis.api_client import APIClient
from analysis.cost_tracker import CostTracker
from core.config import cfg
from core.db import ensure_tables, get_conn
from core.log import get_logger

log = get_logger("jarvis")

PERSONA = (
    "You are JARVIS, the AI analyst for Mediajedi Hedge Fund, a long/short equity "
    "hedge fund. You are precise, measured, and quietly confident — an institutional voice, "
    "never hype. You ground every statement in the provided system snapshot. When you lack "
    "data, say so plainly. Numbers are sector-percentile scores (0-100) unless noted."
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lp_letters (for_date TEXT PRIMARY KEY, content TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS jarvis_commentary (week TEXT PRIMARY KEY, content TEXT, created_at TEXT);
"""


def _one(sql, params=()):
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    return row


def vix() -> tuple[float | None, str]:
    row = _one("SELECT close FROM daily_prices WHERE ticker='^VIX' ORDER BY date DESC LIMIT 1")
    if not row:
        return None, "unknown"
    v = float(row["close"])
    regime = "low" if v < 15 else "normal" if v < 25 else "elevated" if v < 35 else "high"
    return v, regime


def metrics() -> dict:
    """The 10 cover metrics."""
    n = lambda sql, p=(): (_one(sql, p) or {"c": 0})["c"]
    r = _one("SELECT MAX(asof_date) c FROM scores")
    asof = r["c"] if r else None
    v, regime = vix()
    return {
        "universe": n("SELECT COUNT(*) c FROM universe"),
        "long_candidates": n("SELECT COUNT(*) c FROM scores WHERE asof_date=? AND composite>=80", (asof,)),
        "short_candidates": n("SELECT COUNT(*) c FROM scores WHERE asof_date=? AND composite<=20", (asof,)),
        "positions": n("SELECT COUNT(DISTINCT ticker) c FROM target_portfolio"),
        "crowding": n("SELECT COUNT(DISTINCT ticker) c FROM institutional_holdings"),
        "insider_events": n("SELECT COUNT(*) c FROM insider_transactions WHERE transaction_code IN ('P','S')"),
        "ceo_buys": n("SELECT COUNT(*) c FROM insider_transactions WHERE transaction_code='P' AND (insider_title LIKE '%CEO%' OR insider_title LIKE '%Chief Executive%' OR insider_title LIKE '%CFO%')"),
        "cluster_buys": n("SELECT COUNT(*) c FROM insider_transactions WHERE transaction_code='P'"),
        "vix": round(v, 2) if v is not None else None,
        "vix_regime": regime,
        "earnings_7d": n("SELECT COUNT(*) c FROM earnings_calendar WHERE earnings_date<=date('now','+7 day') AND earnings_date>=date('now')"),
        "data_asof": asof,
    }


def snapshot() -> dict:
    """~system-state snapshot used as cached Claude context."""
    r = _one("SELECT MAX(asof_date) c FROM scores")
    asof = r["c"] if r else None
    with get_conn() as conn:
        top = conn.execute(
            "SELECT ticker,sector,composite,momentum,value,quality,growth,piotroski,altman_z "
            "FROM scores WHERE asof_date=? ORDER BY composite DESC LIMIT 15", (asof,)).fetchall()
        bot = conn.execute(
            "SELECT ticker,sector,composite,momentum,value,quality,growth,piotroski,altman_z "
            "FROM scores WHERE asof_date=? ORDER BY composite ASC LIMIT 15", (asof,)).fetchall()
        book = conn.execute(
            "SELECT ticker,side,weight,sector,beta FROM target_portfolio ORDER BY abs(weight) DESC", ()
        ).fetchall()
    return {
        "as_of": datetime.now().isoformat(),
        "fund": cfg.get("fund.name"),
        "metrics": metrics(),
        "top_longs": [dict(r) for r in top],
        "top_shorts": [dict(r) for r in bot],
        "target_book": [dict(r) for r in book],
    }


def _client():
    return APIClient(tracker=CostTracker())


def ask(question: str, history: list[dict] | None = None) -> str:
    """history: list of {role, content}; only the last 6 turns are kept."""
    snap = json.dumps(snapshot(), default=str)
    sys = f"{PERSONA}\n\nCURRENT SYSTEM SNAPSHOT (authoritative):\n{snap}"
    turns = (history or [])[-6:]
    convo = "\n".join(f"{t['role'].upper()}: {t['content']}" for t in turns)
    user = (convo + "\n\n" if convo else "") + f"USER: {question}"
    return _client().complete(sys, user, max_tokens=1200)


def lp_letter(for_date: str | None = None, regenerate: bool = False) -> str:
    ensure_tables(_SCHEMA)
    d = for_date or date.today().isoformat()
    if not regenerate:
        row = _one("SELECT content FROM lp_letters WHERE for_date=?", (d,))
        if row:
            return row["content"]
    snap = json.dumps(snapshot(), default=str)
    sys = PERSONA + "\n\nSNAPSHOT:\n" + snap
    user = (
        "Write today's Daily Investors' Letter as 3-4 short paragraphs. Open with "
        "'Dear Investors,'. Cover: portfolio posture (long/short, gross/net), the "
        "day's notable positioning and any risk flags, and a measured outlook. Institutional, "
        "calm, specific. Do NOT include letterhead or signature — the document frame adds those."
    )
    content = _client().complete(sys, user, max_tokens=1400)
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO lp_letters (for_date,content,created_at) VALUES (?,?,?)",
                     (d, content, datetime.utcnow().isoformat()))
    return content


def weekly_commentary(regenerate: bool = False) -> str:
    ensure_tables(_SCHEMA)
    week = date.today().strftime("%Y-W%U")
    if not regenerate:
        row = _one("SELECT content FROM jarvis_commentary WHERE week=?", (week,))
        if row:
            return row["content"]
    sys = PERSONA + "\n\nSNAPSHOT:\n" + json.dumps(snapshot(), default=str)
    user = ("Write this week's market & portfolio commentary (~4 short paragraphs) in the "
            "JARVIS voice: factor leadership, positioning shifts, risk regime, and what you're "
            "watching next week.")
    content = _client().complete(sys, user, max_tokens=1400)
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO jarvis_commentary (week,content,created_at) VALUES (?,?,?)",
                     (week, content, datetime.utcnow().isoformat()))
    return content
