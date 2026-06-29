"""10-K Risk Factors analysis. Strips HTML, slices Item 1A, caps length.
Output: new_risks, material_risks, boilerplate_percentage, risk_severity, summary.
Returns None if no 10-K is cached for the ticker."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from analysis.base import AnalysisContext, run_cached
from analysis.cache import artifact_hash
from analysis.style import PLAIN_LANGUAGE
from core.config import cfg
from core.db import get_conn

ANALYZER = "risk"

_SYSTEM = (
    "You analyze the Risk Factors (Item 1A) of a 10-K. Separate genuinely material, "
    "company-specific risks from generic boilerplate. Judge overall severity.\n\n"
    "Respond with ONLY a JSON object:\n"
    "{\n"
    '  "material_risks": [<string>...],\n'
    '  "new_risks": [<string>...],\n'
    '  "boilerplate_percentage": <0-100>,\n'
    '  "risk_severity": "LOW"|"MEDIUM"|"HIGH",\n'
    '  "one_line_summary": <string>\n'
    "}"
)
_SYSTEM += "\n\n" + PLAIN_LANGUAGE


def _latest_10k(ticker: str) -> tuple[str, str] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT d.accession, d.content FROM sec_documents d "
            "WHERE d.ticker=? AND d.form='10-K' ORDER BY d.fetched_at DESC LIMIT 1", (ticker,)
        ).fetchone()
    return (row["accession"], row["content"]) if row else None


def _extract_risk_factors(html: str) -> str:
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    # Best-effort slice: "Item 1A ... Risk Factors" up to "Item 1B"/"Item 2"
    m = re.search(r"item\s*1a\.?\s*risk\s*factors", text, re.IGNORECASE)
    if m:
        start = m.start()
        end_m = re.search(r"item\s*1b\.|item\s*2\.", text[start + 50:], re.IGNORECASE)
        end = start + 50 + end_m.start() if end_m else len(text)
        text = text[start:end]
    cap = int(cfg.get("analysis.risk_factors_max_chars", 80000))
    return text[:cap]


def analyze(ctx: AnalysisContext, ticker: str) -> dict | None:
    doc = _latest_10k(ticker)
    if not doc:
        return None
    accession, html = doc
    risk_text = _extract_risk_factors(html)
    if len(risk_text) < 200:
        return None
    artifact_id = artifact_hash(ANALYZER, ticker, accession)
    user = f"Ticker: {ticker}\n10-K Risk Factors:\n{risk_text}"
    return run_cached(ctx, ANALYZER, ticker, artifact_id, _SYSTEM, user)
