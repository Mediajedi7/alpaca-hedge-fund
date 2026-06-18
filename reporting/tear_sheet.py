"""Institutional markdown tear sheet: metrics vs SPY, monthly grid, drawdown,
rolling Sharpe, exposures, turnover. Saved to output/tearsheet_{date}.md."""
from __future__ import annotations

from datetime import date

from core.config import ROOT, cfg
from core.db import get_conn
from reporting import analytics, metrics


def _exposures() -> dict:
    with get_conn() as conn:
        asof = conn.execute("SELECT MAX(asof_date) d FROM target_portfolio").fetchone()["d"]
        rows = conn.execute(
            "SELECT side, weight, sector FROM target_portfolio WHERE asof_date=?", (asof,)).fetchall()
    long_g = sum(r["weight"] for r in rows if r["weight"] > 0)
    short_g = -sum(r["weight"] for r in rows if r["weight"] < 0)
    sect: dict[str, float] = {}
    for r in rows:
        sect[r["sector"]] = sect.get(r["sector"], 0.0) + r["weight"]
    return {"long_gross": long_g, "short_gross": short_g, "sectors": sect}


def generate() -> str:
    m = metrics.summary()
    turn = analytics.turnover(30)
    exp = _exposures()
    mg = metrics.monthly_returns()
    L = [f"# {cfg.get('fund.name')} — Tear Sheet", f"*{date.today():%Y-%m-%d}*", "",
         "## Performance", "", "| Metric | Value |", "|---|---|",
         f"| NAV | {m.get('nav', 'n/a')} |",
         f"| Total return | {m.get('total_return')} |",
         f"| Ann. vol | {m.get('ann_vol')} |",
         f"| Sharpe | {m.get('sharpe')} |",
         f"| Max drawdown | {m.get('max_drawdown')} |",
         f"| History (days) | {m.get('history_days')} |", "",
         "## Exposure", "",
         f"- Long gross: {exp['long_gross']:.0%}  |  Short gross: {exp['short_gross']:.0%}  "
         f"|  Gross: {exp['long_gross'] + exp['short_gross']:.0%}  |  Net: {exp['long_gross'] - exp['short_gross']:+.0%}",
         "", "### Sector net", ""]
    for s, w in sorted(exp["sectors"].items(), key=lambda kv: -abs(kv[1])):
        L.append(f"- {s}: {w:+.1%}")
    L += ["", "## Turnover", "",
          f"- 30d turnover: {turn['turnover']:.1%}  |  annualized: {turn['annualized']:.1f}x  "
          f"|  budget: {turn['budget']}x", ""]
    if not mg.empty:
        L += ["## Monthly returns", "", "```", mg.round(4).to_string(), "```", ""]
    out = "\n".join(L)
    path = ROOT / "output" / f"tearsheet_{date.today():%Y%m%d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out)
    return out
