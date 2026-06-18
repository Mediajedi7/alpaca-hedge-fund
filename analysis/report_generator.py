"""Per-candidate markdown research reports: all scores, Claude summaries, upcoming
catalysts, and risk flags. Saved to output/reports_{timestamp}/{TICKER}.md."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from analysis import cache
from core.config import ROOT
from core.db import get_conn
from core.log import get_logger
from data.earnings_calendar import days_to_earnings

log = get_logger("report_generator")


def _scores(ticker: str) -> dict | None:
    with get_conn() as conn:
        s = conn.execute(
            "SELECT * FROM scores WHERE ticker=? ORDER BY asof_date DESC LIMIT 1", (ticker,)
        ).fetchone()
        c = conn.execute(
            "SELECT quant, claude_fundamental, combined FROM combined_scores WHERE ticker=? "
            "ORDER BY asof_date DESC LIMIT 1", (ticker,)
        ).fetchone()
    if not s:
        return None
    out = dict(s)
    if c:
        out.update({"combined": c["combined"], "claude_fundamental": c["claude_fundamental"]})
    return out


def _md(ticker: str, side: str) -> str | None:
    s = _scores(ticker)
    if not s:
        return None
    claude = cache.all_for_ticker(ticker)
    L = [f"# {ticker} — {side.upper()} candidate", "",
         f"*Generated {datetime.now():%Y-%m-%d %H:%M}*", "",
         "## Scores (0-100 sector percentile)", "",
         "| Factor | Score |", "|---|---|"]
    for f in ("composite", "combined", "claude_fundamental", "momentum", "value", "quality",
              "growth", "revisions", "short_interest", "insider", "institutional"):
        v = s.get(f)
        if v is not None:
            L.append(f"| {f} | {v:.0f} |")
    L += ["", f"**Piotroski F-Score:** {s.get('piotroski', 'n/a')}  |  "
          f"**Altman Z:** {s.get('altman_z') and round(s['altman_z'], 2)}", ""]

    # Catalysts
    dte = days_to_earnings(ticker)
    L += ["## Upcoming catalysts", "",
          f"- Earnings in **{dte} days**" if dte is not None else "- No earnings date within 30 days", ""]

    # Claude analysis
    L.append("## Claude analysis")
    if not claude:
        L += ["", "_No qualitative analysis available (scored on quant only)._"]
    risk_flags = []
    for name, r in claude.items():
        if not isinstance(r, dict):
            continue
        L += ["", f"### {name.title()}", r.get("one_line_summary", "")]
        if name == "filing":
            for rf in r.get("red_flags", []):
                risk_flags.append(f"[filing] {rf}")
        if name == "risk" and str(r.get("risk_severity", "")).upper() == "HIGH":
            risk_flags.append(f"[10-K] HIGH severity: {r.get('one_line_summary', '')}")

    L += ["", "## Risk flags", ""]
    L += [f"- ⚠️ {rf}" for rf in risk_flags] if risk_flags else ["- None flagged"]
    return "\n".join(L)


def generate(longs: list[str], shorts: list[str], timestamp: str | None = None) -> Path:
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "output" / f"reports_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for side, tickers in (("long", longs), ("short", shorts)):
        for t in tickers:
            md = _md(t, side)
            if md:
                (out_dir / f"{t}.md").write_text(md)
                n += 1
    log.info("Wrote %d reports to %s", n, out_dir)
    return out_dir
