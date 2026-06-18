"""Earnings-call transcript analysis. Requires a transcript in the `transcripts`
table (FMP Ultimate-only — NOT available on our Premium plan), so this analyzer is
dormant: it returns None whenever no transcript is cached. Kept implemented so it
activates automatically if transcripts are ever ingested."""
from __future__ import annotations

from analysis.base import AnalysisContext, run_cached
from analysis.cache import artifact_hash
from core.config import cfg
from core.db import ensure_tables, get_conn

ANALYZER = "earnings"

_SYSTEM = (
    "You analyze an earnings-call transcript. Score each category 1-10 and explain.\n\n"
    "Respond with ONLY a JSON object:\n"
    "{\n"
    '  "management_confidence": {"score": <1-10>, "reasoning": <string>},\n'
    '  "revenue_guidance": {"score": <1-10>, "reasoning": <string>},\n'
    '  "margin_trajectory": {"score": <1-10>, "reasoning": <string>},\n'
    '  "competitive_position": {"score": <1-10>, "reasoning": <string>},\n'
    '  "risk_factors": {"score": <1-10>, "reasoning": <string>},\n'
    '  "capital_allocation": {"score": <1-10>, "reasoning": <string>},\n'
    '  "bull_case": <string>, "bear_case": <string>,\n'
    '  "key_quotes": [<string>...], "one_line_summary": <string>\n'
    "}"
)


def _transcript(ticker: str) -> tuple[str, str] | None:
    """Return (transcript_id, text) if a transcript exists, else None."""
    ensure_tables("CREATE TABLE IF NOT EXISTS transcripts "
                  "(ticker TEXT, transcript_id TEXT, content TEXT, PRIMARY KEY(ticker,transcript_id));")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT transcript_id, content FROM transcripts WHERE ticker=? "
            "ORDER BY transcript_id DESC LIMIT 1", (ticker,)
        ).fetchone()
    return (row["transcript_id"], row["content"]) if row else None


def analyze(ctx: AnalysisContext, ticker: str) -> dict | None:
    doc = _transcript(ticker)
    if not doc:
        return None  # dormant: no transcripts on FMP Premium
    tid, text = doc
    cap = int(cfg.get("analysis.earnings_transcript_max_chars", 120000))
    artifact_id = artifact_hash(ANALYZER, ticker, tid)
    user = f"Ticker: {ticker}\nEarnings call transcript:\n{text[:cap]}"
    return run_cached(ctx, ANALYZER, ticker, artifact_id, _SYSTEM, user)
