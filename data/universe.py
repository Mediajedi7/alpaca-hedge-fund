"""Source 1 — Universe. Scrapes the current S&P 500 constituents from Wikipedia
(ticker, company, GICS sector, sub-industry), cached weekly, plus the fixed
benchmark / sector-ETF / macro ticker lists from config."""
from __future__ import annotations

import io
from datetime import datetime, timezone

import pandas as pd
import requests

from core.config import cfg
from core.db import ensure_tables, get_conn, get_meta, set_meta
from core.log import get_logger

log = get_logger("universe")

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_UA = {"User-Agent": "Mozilla/5.0 (MediajediHedgeFund research bot)"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS universe (
    ticker       TEXT PRIMARY KEY,
    company      TEXT,
    sector       TEXT,
    sub_industry TEXT,
    updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_universe_sector ON universe(sector);
"""


def _refresh_due() -> bool:
    last = get_meta("universe_refreshed_at")
    if not last:
        return True
    age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).days
    return age_days >= int(cfg.get("data.universe_refresh_days", 7))


def _scrape_sp500() -> pd.DataFrame:
    resp = requests.get(WIKI_URL, headers=_UA, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    df = tables[0]  # first table = constituents
    df = df.rename(
        columns={
            "Symbol": "ticker",
            "Security": "company",
            "GICS Sector": "sector",
            "GICS Sub-Industry": "sub_industry",
        }
    )[["ticker", "company", "sector", "sub_industry"]]
    # Wikipedia uses '.' for class shares (BRK.B); yfinance wants '-' (BRK-B).
    df["ticker"] = df["ticker"].str.replace(".", "-", regex=False).str.strip()
    return df


def refresh_universe(force: bool = False) -> int:
    """Refresh the S&P 500 universe if stale. Returns number of constituents stored."""
    ensure_tables(_SCHEMA)
    if not force and not _refresh_due():
        with get_conn() as conn:
            n = conn.execute("SELECT COUNT(*) AS c FROM universe").fetchone()["c"]
        log.info("Universe fresh; %d constituents (skipping scrape)", n)
        return n

    df = _scrape_sp500()
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM universe")
        conn.executemany(
            "INSERT OR REPLACE INTO universe(ticker, company, sector, sub_industry, updated_at) "
            "VALUES(?,?,?,?,?)",
            [(r.ticker, r.company, r.sector, r.sub_industry, now) for r in df.itertuples()],
        )
    set_meta("universe_refreshed_at", now)
    log.info("Universe refreshed: %d S&P 500 constituents", len(df))
    return len(df)


def get_universe_tickers() -> list[str]:
    ensure_tables(_SCHEMA)
    with get_conn() as conn:
        rows = conn.execute("SELECT ticker FROM universe ORDER BY ticker").fetchall()
    return [r["ticker"] for r in rows]


def get_sector_map() -> dict[str, str]:
    """ticker -> GICS sector (used everywhere for sector-relative ranking)."""
    ensure_tables(_SCHEMA)
    with get_conn() as conn:
        rows = conn.execute("SELECT ticker, sector FROM universe").fetchall()
    return {r["ticker"]: r["sector"] for r in rows}


def benchmark_tickers() -> list[str]:
    return list(cfg.get("data.benchmarks", []))


def sector_etfs() -> list[str]:
    return list(cfg.get("data.sector_etfs", []))


def macro_tickers() -> list[str]:
    return list(cfg.get("data.macro_tickers", []))


def all_price_tickers() -> list[str]:
    """Everything we need daily OHLCV for: universe + benchmarks + sector ETFs + macro."""
    extra = benchmark_tickers() + sector_etfs() + macro_tickers()
    seen, out = set(), []
    for t in get_universe_tickers() + extra:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


if __name__ == "__main__":
    n = refresh_universe(force=True)
    print(f"Stored {n} constituents; {len(all_price_tickers())} total price tickers")
