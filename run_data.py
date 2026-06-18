#!/usr/bin/env python3
"""Layer 1 entry point — refresh all data sources into SQLite.

Usage:
  python3 run_data.py                      # full refresh (all sources)
  python3 run_data.py --no-filings --no-13f  # fast daily refresh (skip heavy SEC)
  python3 run_data.py --forms 10-K 8-K     # selective filing forms
  python3 run_data.py --tickers AAPL MSFT  # restrict to a subset (testing)
"""
from __future__ import annotations

import argparse
import time

from core.log import get_logger
from data import (
    earnings_calendar,
    estimates,
    fundamentals,
    institutional,
    market_data,
    sec_data,
    short_interest,
    universe,
)

log = get_logger("run_data")


def refresh(no_filings: bool = False, no_13f: bool = False, forms: list[str] | None = None,
            tickers: list[str] | None = None, skip_fundamentals: bool = False,
            sleep: float = 0.0) -> None:
    """Run the Layer 1 data refresh. Shared by run_data.py and run_scoring.py."""
    t0 = time.time()
    universe.refresh_universe()
    tk = tickers or universe.get_universe_tickers()
    price_tickers = tickers or universe.all_price_tickers()

    market_data.update_prices(price_tickers, sleep=sleep)
    if not skip_fundamentals:
        fundamentals.update_fundamentals(tk, sleep=sleep)
    short_interest.update_short_interest(tk, sleep=sleep)
    estimates.update_estimates(tk, sleep=sleep)
    earnings_calendar.update_earnings_calendar(tk, sleep=sleep)

    if not no_filings:
        sec_data.update_filings(tk, forms=forms)
        sec_data.update_form4(tk)
    if not no_13f:
        institutional.update_institutional()

    log.info("Layer 1 data refresh complete in %.1fs", time.time() - t0)


def main() -> None:
    ap = argparse.ArgumentParser(description="Mediajedi Layer 1 data refresh")
    ap.add_argument("--no-filings", action="store_true", help="skip SEC 10-K/10-Q/8-K + Form 4")
    ap.add_argument("--no-13f", action="store_true", help="skip 13-F institutional holdings")
    ap.add_argument("--forms", nargs="+", default=None, help="restrict SEC filings to these forms")
    ap.add_argument("--tickers", nargs="+", default=None, help="restrict to a subset of tickers")
    ap.add_argument("--skip-fundamentals", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.0, help="politeness delay between API calls")
    args = ap.parse_args()
    refresh(args.no_filings, args.no_13f, args.forms, args.tickers,
            args.skip_fundamentals, args.sleep)


if __name__ == "__main__":
    main()
