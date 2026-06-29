"""Forensic accounting review over 8 quarters of fundamentals.
Output: earnings_quality_score, balance_sheet_score, red/green flags, risk_level."""
from __future__ import annotations

import json

from analysis.base import AnalysisContext, run_cached
from analysis.cache import artifact_hash
from analysis.style import PLAIN_LANGUAGE
from core.db import get_conn

ANALYZER = "filing"

_SYSTEM = (
    "You are a forensic accountant reviewing a company's last 8 quarters of fundamentals. "
    "Focus on earnings quality (CFO vs net income), revenue quality (accounts receivable vs "
    "revenue), balance-sheet health, and accruals. Be skeptical and specific.\n\n"
    "Respond with ONLY a JSON object:\n"
    "{\n"
    '  "earnings_quality_score": <0-10>,\n'
    '  "balance_sheet_score": <0-10>,\n'
    '  "red_flags": [<string>...],\n'
    '  "green_flags": [<string>...],\n'
    '  "risk_level": "LOW"|"MEDIUM"|"HIGH",\n'
    '  "one_line_summary": <string>\n'
    "}"
)
_SYSTEM += "\n\n" + PLAIN_LANGUAGE

_COLS = ["period_end", "revenue", "net_income", "operating_cash_flow", "free_cash_flow",
         "gross_margin", "net_margin", "cfo_to_ni", "accruals_ratio", "ar_to_revenue",
         "debt_to_equity", "current_ratio", "roe", "roa"]


def _fundamentals(ticker: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {','.join(_COLS)} FROM fundamentals WHERE ticker=? AND period_type='Q' "
            "ORDER BY period_end DESC LIMIT 8", (ticker,)
        ).fetchall()
    return [dict(r) for r in rows]


def analyze(ctx: AnalysisContext, ticker: str) -> dict | None:
    rows = _fundamentals(ticker)
    if not rows:
        return None
    artifact_id = artifact_hash(ANALYZER, ticker, rows[0]["period_end"])
    user = (f"Ticker: {ticker}\nLast 8 quarters (most recent first):\n"
            f"{json.dumps(rows, indent=2, default=str)}")
    return run_cached(ctx, ANALYZER, ticker, artifact_id, _SYSTEM, user)
