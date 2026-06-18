"""Combined score = 60% quantitative composite (Layer 2) + 40% Claude fundamental
(average of available analyzers, normalized 0-100). If no Claude analysis exists for
a ticker, it falls back to 100% quant with no penalty. Re-ranked within sector."""
from __future__ import annotations

import pandas as pd

from analysis import cache
from core.config import cfg
from core.db import ensure_tables, get_conn
from core.log import get_logger
from data.universe import get_sector_map
from factors.base import sector_percentile

log = get_logger("combined_score")

_SIGNAL = {"STRONG_BUY": 100, "BUY": 75, "NEUTRAL": 50, "SELL": 25, "STRONG_SELL": 0}
_SEVERITY = {"LOW": 80, "MEDIUM": 50, "HIGH": 20}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS combined_scores (
    asof_date TEXT, ticker TEXT, sector TEXT,
    quant REAL, claude_fundamental REAL, combined REAL,
    PRIMARY KEY (asof_date, ticker)
);
"""


def claude_fundamental(results: dict[str, dict]) -> float | None:
    """Map cached analyzer outputs to a single 0-100 score (avg of available)."""
    parts = []
    if "filing" in results:
        f = results["filing"]
        eq, bs = f.get("earnings_quality_score"), f.get("balance_sheet_score")
        vals = [v for v in (eq, bs) if isinstance(v, (int, float))]
        if vals:
            parts.append(sum(vals) / len(vals) * 10)
    if "insider" in results:
        parts.append(_SIGNAL.get(str(results["insider"].get("signal_strength", "")).upper(), 50))
    if "risk" in results:
        parts.append(_SEVERITY.get(str(results["risk"].get("risk_severity", "")).upper(), 50))
    if "earnings" in results:
        cats = ["management_confidence", "revenue_guidance", "margin_trajectory",
                "competitive_position", "risk_factors", "capital_allocation"]
        scores = [results["earnings"][c]["score"] for c in cats
                  if isinstance(results["earnings"].get(c), dict) and "score" in results["earnings"][c]]
        if scores:
            parts.append(sum(scores) / len(scores) * 10)
    return sum(parts) / len(parts) if parts else None


def _latest_asof() -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT MAX(asof_date) d FROM scores").fetchone()
    return row["d"] if row else None


def compute(persist: bool = True) -> pd.DataFrame:
    asof = _latest_asof()
    if not asof:
        raise RuntimeError("no quant scores found — run Layer 2 first")
    with get_conn() as conn:
        quant = pd.read_sql_query(
            "SELECT ticker, sector, composite FROM scores WHERE asof_date=?", conn, params=(asof,)
        ).set_index("ticker")

    qw = float(cfg.get("analysis.combine.quant_weight", 0.6))
    cw = float(cfg.get("analysis.combine.claude_weight", 0.4))
    sector_map = get_sector_map()

    claude_vals, combined_raw = {}, {}
    for t, row in quant.iterrows():
        cf = claude_fundamental(cache.all_for_ticker(t))
        claude_vals[t] = cf
        combined_raw[t] = (qw * row["composite"] + cw * cf) if cf is not None else row["composite"]

    out = quant.copy()
    out["claude_fundamental"] = pd.Series(claude_vals)
    out["combined"] = sector_percentile(pd.Series(combined_raw), sector_map, True)

    if persist:
        ensure_tables(_SCHEMA)
        with get_conn() as conn:
            conn.execute("DELETE FROM combined_scores WHERE asof_date=?", (asof,))
            conn.executemany(
                "INSERT INTO combined_scores (asof_date,ticker,sector,quant,claude_fundamental,combined) "
                "VALUES (?,?,?,?,?,?)",
                [(asof, t, r.sector, r.composite,
                  None if pd.isna(r.claude_fundamental) else r.claude_fundamental, r.combined)
                 for t, r in out.iterrows()],
            )
        n_claude = sum(1 for v in claude_vals.values() if v is not None)
        log.info("Combined scores stored for %d tickers (%d with Claude analysis), asof %s",
                 len(out), n_claude, asof)
    return out
