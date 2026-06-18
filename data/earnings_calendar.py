"""Source 7 — Earnings Calendar. Upcoming earnings dates within the next N days
(config: data.earnings_calendar_horizon_days) across the universe. Used by the
earnings blackout rule (Layer 5) and the half-size rule (Layer 4)."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf

from core.config import cfg
from core.db import ensure_tables, get_conn, set_meta
from core.log import get_logger
from data.universe import get_universe_tickers

log = get_logger("earnings_calendar")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS earnings_calendar (
    ticker        TEXT,
    earnings_date TEXT,
    updated_at    TEXT,
    PRIMARY KEY (ticker, earnings_date)
);
"""


def _next_earnings_dates(ticker: str) -> list[date]:
    """Return upcoming earnings date(s) for a ticker via yfinance calendar."""
    try:
        cal = yf.Ticker(ticker).calendar
    except Exception as e:  # noqa: BLE001
        log.warning("calendar fetch failed for %s: %s", ticker, e)
        return []
    raw = None
    if isinstance(cal, dict):
        raw = cal.get("Earnings Date")
    elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
        raw = cal.loc["Earnings Date"].tolist()
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raw = [raw]
    out = []
    for d in raw:
        try:
            out.append(pd.Timestamp(d).date())
        except Exception:  # noqa: BLE001
            continue
    return out


def update_earnings_calendar(tickers: list[str] | None = None, sleep: float = 0.0) -> int:
    ensure_tables(_SCHEMA)
    tickers = tickers or get_universe_tickers()
    horizon = int(cfg.get("data.earnings_calendar_horizon_days", 30))
    today = date.today()
    cutoff = today + timedelta(days=horizon)
    now = datetime.utcnow().isoformat()

    # Clear stale future rows so the table reflects the current horizon snapshot.
    with get_conn() as conn:
        conn.execute("DELETE FROM earnings_calendar WHERE earnings_date >= ?", (today.isoformat(),))

    stored = 0
    for i, t in enumerate(tickers, 1):
        for d in _next_earnings_dates(t):
            if today <= d <= cutoff:
                with get_conn() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO earnings_calendar (ticker,earnings_date,updated_at) "
                        "VALUES (?,?,?)",
                        (t, d.isoformat(), now),
                    )
                stored += 1
        if i % 50 == 0:
            log.info("earnings_calendar: %d/%d tickers", i, len(tickers))
        if sleep:
            time.sleep(sleep)
    set_meta("earnings_calendar_updated_at", now)
    log.info("Earnings calendar: %d upcoming events within %d days", stored, horizon)
    return stored


def days_to_earnings(ticker: str) -> int | None:
    """Calendar days until the ticker's next stored earnings date (None if unknown)."""
    ensure_tables(_SCHEMA)
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MIN(earnings_date) AS d FROM earnings_calendar WHERE ticker=? AND earnings_date>=?",
            (ticker, today),
        ).fetchone()
    if not row or not row["d"]:
        return None
    return (date.fromisoformat(row["d"]) - date.today()).days


if __name__ == "__main__":
    import sys
    test = sys.argv[1:] or ["AAPL", "MSFT", "JPM"]
    n = update_earnings_calendar(test)
    print(f"Stored {n} upcoming earnings events for {test}")
