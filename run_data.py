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


def main() -> None:
    ap = argparse.ArgumentParser(description="Meridian Layer 1 data refresh")
    ap.add_argument("--no-filings", action="store_true", help="skip SEC 10-K/10-Q/8-K + Form 4")
    ap.add_argument("--no-13f", action="store_true", help="skip 13-F institutional holdings")
    ap.add_argument("--forms", nargs="+", default=None, help="restrict SEC filings to these forms")
    ap.add_argument("--tickers", nargs="+", default=None, help="restrict to a subset of tickers")
    ap.add_argument("--skip-fundamentals", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.0, help="politeness delay between API calls")
    args = ap.parse_args()

    t0 = time.time()
    universe.refresh_universe()
    tickers = args.tickers or universe.get_universe_tickers()

    price_tickers = args.tickers or universe.all_price_tickers()
    market_data.update_prices(price_tickers, sleep=args.sleep)

    if not args.skip_fundamentals:
        fundamentals.update_fundamentals(tickers, sleep=args.sleep)

    short_interest.update_short_interest(tickers, sleep=args.sleep)
    estimates.update_estimates(tickers, sleep=args.sleep)
    earnings_calendar.update_earnings_calendar(tickers, sleep=args.sleep)

    if not args.no_filings:
        sec_data.update_filings(tickers, forms=args.forms)
        sec_data.update_form4(tickers)

    if not args.no_13f:
        institutional.update_institutional()

    log.info("Layer 1 data refresh complete in %.1fs", time.time() - t0)


if __name__ == "__main__":
    main()
