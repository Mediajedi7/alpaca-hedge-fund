"""Form 4 interpretation (last 90 days): routine selling vs meaningful buying.
Output: signal_strength, confidence, key_transactions, reasoning, summary.
Returns None if no insider data exists for the ticker."""
from __future__ import annotations

import json
from datetime import date, timedelta

from analysis.base import AnalysisContext, run_cached
from analysis.cache import artifact_hash
from analysis.style import PLAIN_LANGUAGE
from core.db import get_conn

ANALYZER = "insider"

_SYSTEM = (
    "You interpret insider Form 4 activity over the last 90 days. Distinguish routine, "
    "pre-scheduled selling (e.g. 10b5-1, option-exercise tax) from discretionary, "
    "conviction-signaling open-market purchases. Code P = open-market buy, S = open-market "
    "sale; A/M/F are grants/exercises/tax and are weak signals.\n\n"
    "Respond with ONLY a JSON object:\n"
    "{\n"
    '  "signal_strength": "STRONG_BUY"|"BUY"|"NEUTRAL"|"SELL"|"STRONG_SELL",\n'
    '  "confidence": <0-1>,\n'
    '  "key_transactions": [<string>...],\n'
    '  "reasoning": <string>,\n'
    '  "one_line_summary": <string>\n'
    "}"
)
_SYSTEM += "\n\n" + PLAIN_LANGUAGE


def _transactions(ticker: str) -> list[dict]:
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT insider_name, insider_title, transaction_type, transaction_code, "
            "shares, price, date FROM insider_transactions WHERE ticker=? AND date>=? "
            "ORDER BY date DESC LIMIT 100", (ticker, cutoff)
        ).fetchall()
    return [dict(r) for r in rows]


def analyze(ctx: AnalysisContext, ticker: str) -> dict | None:
    txns = _transactions(ticker)
    if not txns:
        return None
    artifact_id = artifact_hash(ANALYZER, ticker, txns)
    user = (f"Ticker: {ticker}\nForm 4 transactions (last 90 days):\n"
            f"{json.dumps(txns, indent=2, default=str)}")
    return run_cached(ctx, ANALYZER, ticker, artifact_id, _SYSTEM, user)
