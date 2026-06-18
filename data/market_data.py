"""Source 2a — Market Data. Daily OHLCV via yfinance for the full price universe,
with a 3-year lookback and incremental updates (only fetch dates after the last
stored bar per ticker)."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf

from core.config import cfg
from core.db import ensure_tables, get_conn, set_meta
from core.log import get_logger
from data.universe import all_price_tickers

log = get_logger("market_data")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_prices (
    ticker    TEXT,
    date      TEXT,
    open      REAL,
    high      REAL,
    low       REAL,
    close     REAL,
    adj_close REAL,
    volume    INTEGER,
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_prices_date ON daily_prices(date);
"""


def _last_dates() -> dict[str, str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ticker, MAX(date) AS d FROM daily_prices GROUP BY ticker"
        ).fetchall()
    return {r["ticker"]: r["d"] for r in rows}


def _fetch_one(ticker: str, start: date) -> pd.DataFrame:
    df = yf.Ticker(ticker).history(
        start=start.isoformat(), auto_adjust=False, actions=False, raise_errors=False
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.reset_index()
    df["date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
    return df.rename(
        columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Adj Close": "adj_close", "Volume": "volume",
        }
    )[["date", "open", "high", "low", "close", "adj_close", "volume"]]


def update_prices(tickers: list[str] | None = None, sleep: float = 0.0) -> int:
    """Incrementally update daily OHLCV. Returns number of rows inserted."""
    ensure_tables(_SCHEMA)
    tickers = tickers or all_price_tickers()
    lookback = int(cfg.get("data.price_lookback_days", 1095))
    default_start = date.today() - timedelta(days=lookback)
    last = _last_dates()

    inserted = 0
    for i, t in enumerate(tickers, 1):
        if t in last:
            start = datetime.strptime(last[t], "%Y-%m-%d").date() + timedelta(days=1)
            if start > date.today():
                continue
        else:
            start = default_start
        try:
            df = _fetch_one(t, start)
        except Exception as e:  # noqa: BLE001 - one bad ticker shouldn't abort the run
            log.warning("price fetch failed for %s: %s", t, e)
            continue
        if df.empty:
            continue
        with get_conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO daily_prices "
                "(ticker,date,open,high,low,close,adj_close,volume) VALUES (?,?,?,?,?,?,?,?)",
                [(t, r.date, r.open, r.high, r.low, r.close, r.adj_close, int(r.volume or 0))
                 for r in df.itertuples()],
            )
        inserted += len(df)
        if i % 50 == 0:
            log.info("prices: %d/%d tickers (%d rows so far)", i, len(tickers), inserted)
        if sleep:
            time.sleep(sleep)

    set_meta("prices_updated_at", datetime.utcnow().isoformat())
    log.info("Prices updated: %d rows across %d tickers", inserted, len(tickers))
    return inserted


def get_prices(ticker: str, lookback_days: int | None = None) -> pd.DataFrame:
    ensure_tables(_SCHEMA)
    q = "SELECT * FROM daily_prices WHERE ticker=? ORDER BY date"
    with get_conn() as conn:
        df = pd.read_sql_query(q, conn, params=(ticker,))
    if lookback_days and not df.empty:
        df = df.tail(lookback_days)
    return df


if __name__ == "__main__":
    import sys
    test = sys.argv[1:] or ["AAPL", "MSFT", "SPY"]
    rows = update_prices(test)
    print(f"Inserted {rows} rows for {test}")
