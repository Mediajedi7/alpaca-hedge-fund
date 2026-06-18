"""Source 6 — Analyst Estimates. Daily snapshots of forward EPS estimate and
consensus price target via yfinance .info. The Layer 2 revisions factor needs
30+ days of these snapshots to compute 30/60/90-day deltas."""
from __future__ import annotations

import time
from datetime import date, datetime

import yfinance as yf

from core.db import ensure_tables, get_conn, set_meta
from core.log import get_logger
from data.universe import get_universe_tickers

log = get_logger("estimates")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyst_estimates (
    ticker       TEXT,
    date         TEXT,
    forward_eps  REAL,
    price_target REAL,
    updated_at   TEXT,
    PRIMARY KEY (ticker, date)
);
"""


def update_estimates(tickers: list[str] | None = None, sleep: float = 0.0) -> int:
    ensure_tables(_SCHEMA)
    tickers = tickers or get_universe_tickers()
    today = date.today().isoformat()
    now = datetime.utcnow().isoformat()
    stored = 0
    for i, t in enumerate(tickers, 1):
        try:
            info = yf.Ticker(t).info or {}
        except Exception as e:  # noqa: BLE001
            log.warning("info fetch failed for %s: %s", t, e)
            continue
        fwd = info.get("forwardEps")
        tgt = info.get("targetMeanPrice")
        if fwd is None and tgt is None:
            continue
        with get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO analyst_estimates "
                "(ticker,date,forward_eps,price_target,updated_at) VALUES (?,?,?,?,?)",
                (t, today, fwd, tgt, now),
            )
        stored += 1
        if i % 50 == 0:
            log.info("estimates: %d/%d tickers", i, len(tickers))
        if sleep:
            time.sleep(sleep)
    set_meta("estimates_updated_at", now)
    log.info("Analyst-estimate snapshots: %d tickers", stored)
    return stored


if __name__ == "__main__":
    import sys
    test = sys.argv[1:] or ["AAPL", "MSFT", "NVDA"]
    n = update_estimates(test)
    print(f"Stored {n} estimate snapshots for {test}")
