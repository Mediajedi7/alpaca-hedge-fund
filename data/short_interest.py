"""Source 5 — Short Interest. Daily snapshots of shares short / short ratio /
short percent of float via yfinance .info. Stored per (ticker, date) so the
short-interest *change* sub-factor (Layer 2) can compute period-over-period deltas."""
from __future__ import annotations

import time
from datetime import date, datetime

import yfinance as yf

from core.db import ensure_tables, get_conn, set_meta
from core.log import get_logger
from data.universe import get_universe_tickers

log = get_logger("short_interest")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS short_interest (
    ticker              TEXT,
    date                TEXT,
    shares_short        REAL,
    short_ratio         REAL,
    short_percent_float REAL,
    updated_at          TEXT,
    PRIMARY KEY (ticker, date)
);
"""


def _info(ticker: str) -> dict:
    try:
        return yf.Ticker(ticker).info or {}
    except Exception as e:  # noqa: BLE001
        log.warning("info fetch failed for %s: %s", ticker, e)
        return {}


def update_short_interest(tickers: list[str] | None = None, sleep: float = 0.0) -> int:
    ensure_tables(_SCHEMA)
    tickers = tickers or get_universe_tickers()
    today = date.today().isoformat()
    now = datetime.utcnow().isoformat()
    stored = 0
    for i, t in enumerate(tickers, 1):
        info = _info(t)
        ss = info.get("sharesShort")
        sr = info.get("shortRatio")
        spf = info.get("shortPercentOfFloat")
        if ss is None and sr is None and spf is None:
            continue
        with get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO short_interest "
                "(ticker,date,shares_short,short_ratio,short_percent_float,updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (t, today, ss, sr, spf, now),
            )
        stored += 1
        if i % 50 == 0:
            log.info("short_interest: %d/%d tickers", i, len(tickers))
        if sleep:
            time.sleep(sleep)
    set_meta("short_interest_updated_at", now)
    log.info("Short interest snapshots: %d tickers", stored)
    return stored


if __name__ == "__main__":
    import sys
    test = sys.argv[1:] or ["AAPL", "TSLA", "GME"]
    n = update_short_interest(test)
    print(f"Stored {n} short-interest snapshots for {test}")
