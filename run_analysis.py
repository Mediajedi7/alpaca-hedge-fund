#!/usr/bin/env python3
"""Layer 3 entry point — Claude qualitative analysis.

Usage:
  python3 run_analysis.py --estimate-cost      # predict full-run cost, no API calls
  python3 run_analysis.py --ticker AAPL        # analyze one ticker (all analyzers)
  python3 run_analysis.py --sector "Information Technology"
  python3 run_analysis.py                       # full run: top/bottom candidates + reports
"""
from __future__ import annotations

import argparse
import json

from analysis import (
    combined_score,
    earnings_analyzer,
    filing_analyzer,
    insider_analyzer,
    report_generator,
    risk_analyzer,
    sector_analysis,
)
from analysis.base import AnalysisContext
from analysis.cost_tracker import CostCeilingExceeded
from core.config import cfg
from core.db import get_conn
from core.log import get_logger

log = get_logger("run_analysis")

ANALYZERS = [filing_analyzer, risk_analyzer, insider_analyzer, earnings_analyzer]


def _latest_asof() -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT MAX(asof_date) d FROM scores").fetchone()
    return row["d"] if row else None


def _candidates(n: int) -> tuple[list[str], list[str]]:
    asof = _latest_asof()
    if not asof:
        raise RuntimeError("no quant scores — run Layer 2 first")
    with get_conn() as conn:
        longs = [r["ticker"] for r in conn.execute(
            "SELECT ticker FROM scores WHERE asof_date=? ORDER BY composite DESC LIMIT ?", (asof, n))]
        shorts = [r["ticker"] for r in conn.execute(
            "SELECT ticker FROM scores WHERE asof_date=? ORDER BY composite ASC LIMIT ?", (asof, n))]
    return longs, shorts


def analyze_ticker(ctx: AnalysisContext, ticker: str) -> dict:
    results = {}
    for mod in ANALYZERS:
        r = mod.analyze(ctx, ticker)
        if r is not None:
            results[mod.ANALYZER] = r
    return results


def _estimate_cost() -> None:
    n = int(cfg.get("analysis.candidates_per_side", 20))
    longs, shorts = _candidates(n)
    cand = longs + shorts
    qs = "(" + ",".join("?" * len(cand)) + ")"
    with get_conn() as conn:
        has_10k = conn.execute(
            f"SELECT COUNT(DISTINCT ticker) c FROM sec_documents WHERE form='10-K' AND ticker IN {qs}",
            cand).fetchone()["c"]
        has_insider = conn.execute(
            f"SELECT COUNT(DISTINCT ticker) c FROM insider_transactions WHERE ticker IN {qs}",
            cand).fetchone()["c"]
    model = cfg.get("analysis.model")
    p = cfg.get("analysis.pricing", {}).get(model, {"input": 3.0, "output": 15.0})
    # rough avg tokens per analyzer (input, output)
    profile = {"filing": (len(cand), 2500, 700), "risk": (has_10k, 22000, 800),
               "insider": (has_insider, 1500, 600)}
    total = 0.0
    print(f"Full-run estimate — {len(cand)} candidates ({len(longs)}L/{len(shorts)}S), model {model}:")
    for name, (count, ti, to) in profile.items():
        cost = count * (ti * p["input"] + to * p["output"]) / 1_000_000
        total += cost
        print(f"  {name:8s}: {count:3d} calls  ~${cost:.2f}")
    print(f"  earnings: dormant (no transcripts on FMP Premium)")
    print(f"  TOTAL (cold cache): ~${total:.2f}   (ceiling ${cfg.get('analysis.cost_ceiling_usd')})")


def main() -> None:
    ap = argparse.ArgumentParser(description="Mediajedi Layer 3 AI analysis")
    ap.add_argument("--estimate-cost", action="store_true")
    ap.add_argument("--ticker", default=None)
    ap.add_argument("--sector", default=None)
    args = ap.parse_args()

    if args.estimate_cost:
        _estimate_cost()
        return

    ctx = AnalysisContext.create()
    try:
        if args.ticker:
            res = analyze_ticker(ctx, args.ticker)
            print(json.dumps(res, indent=2))
        elif args.sector:
            res = sector_analysis.analyze(ctx, args.sector, _latest_asof())
            print(json.dumps(res, indent=2))
        else:
            n = int(cfg.get("analysis.candidates_per_side", 20))
            longs, shorts = _candidates(n)
            log.info("Full run: %d long + %d short candidates", len(longs), len(shorts))
            for t in longs + shorts:
                analyze_ticker(ctx, t)
            combined_score.compute()
            for sector in {r for r in _sectors_of(longs + shorts)}:
                sector_analysis.analyze(ctx, sector, _latest_asof())
            out_dir = report_generator.generate(longs, shorts)
            print(f"Reports: {out_dir}")
    except CostCeilingExceeded as e:
        log.error("ABORTED: %s", e)
    finally:
        log.info("Cost summary: %s", ctx.tracker.summary())


def _sectors_of(tickers: list[str]) -> set[str]:
    qs = "(" + ",".join("?" * len(tickers)) + ")"
    asof = _latest_asof()
    with get_conn() as conn:
        return {r["sector"] for r in conn.execute(
            f"SELECT DISTINCT sector FROM scores WHERE asof_date=? AND ticker IN {qs}",
            [asof, *tickers])}


if __name__ == "__main__":
    main()
