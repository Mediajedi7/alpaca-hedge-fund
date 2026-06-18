"""Per-sector synthesis: gather Claude + quant results for a sector's analyzed names
and rank them. Output: rankings with reasoning, top_long_idea, top_short_idea, outlook."""
from __future__ import annotations

import json

from analysis import cache
from analysis.base import AnalysisContext, run_cached
from analysis.cache import artifact_hash
from core.db import get_conn

ANALYZER = "sector"

_SYSTEM = (
    "You are a sector strategist. Given per-name quantitative scores and the available "
    "qualitative (Claude) analysis for one GICS sector, rank the names by fundamental "
    "quality and positioning, and pick the best long and short ideas.\n\n"
    "Respond with ONLY a JSON object:\n"
    "{\n"
    '  "rankings": [{"ticker": <string>, "rank": <int>, "reasoning": <string>}...],\n'
    '  "top_long_idea": {"ticker": <string>, "thesis": <string>},\n'
    '  "top_short_idea": {"ticker": <string>, "thesis": <string>},\n'
    '  "sector_outlook": <string>\n'
    "}"
)


def _sector_names(sector: str, asof: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ticker, composite, momentum, value, quality, growth FROM scores "
            "WHERE asof_date=? AND sector=? ORDER BY composite DESC", (asof, sector)
        ).fetchall()
    return [dict(r) for r in rows]


def analyze(ctx: AnalysisContext, sector: str, asof: str) -> dict | None:
    names = _sector_names(sector, asof)
    if not names:
        return None
    payload = []
    for n in names:
        entry = {"ticker": n["ticker"], "quant": n}
        cl = cache.all_for_ticker(n["ticker"])
        if cl:
            entry["claude"] = {k: v.get("one_line_summary") for k, v in cl.items()
                               if isinstance(v, dict)}
        payload.append(entry)

    artifact_id = artifact_hash(ANALYZER, sector, asof, [n["ticker"] for n in names])
    user = (f"Sector: {sector}\nNames (quant-ranked):\n{json.dumps(payload, indent=2, default=str)}")
    # ticker field is the sector key for storage
    return run_cached(ctx, ANALYZER, sector, artifact_id, _SYSTEM, user, max_tokens=4000)
