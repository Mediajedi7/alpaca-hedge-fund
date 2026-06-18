#!/usr/bin/env python3
"""Layer 2 entry point (and daily cron job) — refresh data, then score all factors.

Usage:
  python3 run_scoring.py --no-filings --no-13f   # daily: fast refresh + score
  python3 run_scoring.py --skip-data             # score only (use existing data)
  python3 run_scoring.py --tickers AAPL MSFT     # subset (testing)
"""
from __future__ import annotations

import argparse

import run_data
from core.log import get_logger
from factors.base import ScoringContext
from factors.composite import score_all

log = get_logger("run_scoring")


def main() -> None:
    ap = argparse.ArgumentParser(description="Mediajedi Layer 2 scoring")
    ap.add_argument("--no-filings", action="store_true")
    ap.add_argument("--no-13f", action="store_true")
    ap.add_argument("--forms", nargs="+", default=None)
    ap.add_argument("--tickers", nargs="+", default=None)
    ap.add_argument("--skip-data", action="store_true", help="skip the data refresh, score only")
    ap.add_argument("--sleep", type=float, default=0.0)
    args = ap.parse_args()

    if not args.skip_data:
        run_data.refresh(args.no_filings, args.no_13f, args.forms, args.tickers, sleep=args.sleep)

    ctx = ScoringContext.load()
    scores = score_all(ctx)

    ranked = scores.sort_values("composite", ascending=False)
    log.info("Top 5 composite: %s",
             ", ".join(f"{t}({r.composite:.0f})" for t, r in ranked.head(5).iterrows()))
    log.info("Bottom 5 composite: %s",
             ", ".join(f"{t}({r.composite:.0f})" for t, r in ranked.tail(5).iterrows()))


if __name__ == "__main__":
    main()
