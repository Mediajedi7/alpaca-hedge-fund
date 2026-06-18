"""Shared scoring infrastructure: sector-percentile ranking, the GICS->sector-ETF
map, a ScoringContext that preloads all Layer-1 data once, and score storage.

Convention: every score is a 0-100 percentile rank WITHIN the stock's GICS sector.
Missing data -> 50 (sector median). Sub-factor scores are equal-weighted into a
parent raw score, which is then re-ranked within sector (see combine_subfactors)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from core.db import ensure_tables, get_conn
from core.log import get_logger

log = get_logger("factors")

# GICS sector (as scraped from Wikipedia) -> sector ETF ticker
SECTOR_ETF = {
    "Information Technology": "XLK",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Communication Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
}

NO_DATA = 50.0  # sector-median fallback


def sector_percentile(values: pd.Series, sector_map: dict[str, str],
                      higher_is_better: bool = True) -> pd.Series:
    """Rank `values` (index = ticker) to 0-100 percentile within each GICS sector.
    NaN -> 50. `higher_is_better=False` inverts (low raw value = high score)."""
    df = pd.DataFrame({"value": values})
    df["sector"] = df.index.map(sector_map)
    out = pd.Series(NO_DATA, index=df.index, dtype=float)
    for sector, grp in df.groupby("sector"):
        vals = grp["value"].dropna()
        if len(vals) == 0:
            continue
        if len(vals) == 1:
            out.loc[vals.index] = NO_DATA
            continue
        pct = vals.rank(ascending=higher_is_better, pct=True) * 100.0
        out.loc[pct.index] = pct
    return out


def combine_subfactors(subscores: pd.DataFrame, sector_map: dict[str, str]) -> pd.Series:
    """Equal-weight the sub-factor scores (skip NaN), then re-rank the mean within
    sector to a clean 0-100 parent percentile."""
    raw = subscores.mean(axis=1, skipna=True)
    return sector_percentile(raw, sector_map, higher_is_better=True)


def _ret(arr: np.ndarray, n: int) -> float:
    """Simple return over the last n trading days: arr[-1]/arr[-1-n] - 1."""
    if arr is None or len(arr) <= n or arr[-1 - n] == 0:
        return np.nan
    return arr[-1] / arr[-1 - n] - 1.0


def _ret_between(arr: np.ndarray, near: int, far: int) -> float:
    """Return from far days ago to near days ago (e.g. 12-1m: near=21, far=252)."""
    if arr is None or len(arr) <= far or arr[-1 - far] == 0:
        return np.nan
    return arr[-1 - near] / arr[-1 - far] - 1.0


@dataclass
class ScoringContext:
    asof: str
    tickers: list[str]
    sector_map: dict[str, str]
    prices: dict[str, np.ndarray]                 # ticker -> adj_close chronological
    fund_latest_q: dict[str, pd.Series]           # latest quarterly fundamentals row
    fund_hist_q: dict[str, pd.DataFrame]          # all quarterly rows, ascending
    estimates: dict[str, pd.DataFrame] = field(default_factory=dict)
    short_latest: dict[str, pd.Series] = field(default_factory=dict)
    short_prior: dict[str, pd.Series] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "ScoringContext":
        from data.universe import get_sector_map

        sector_map = get_sector_map()
        tickers = sorted(sector_map.keys())
        etfs = set(SECTOR_ETF.values())

        with get_conn() as conn:
            prices_df = pd.read_sql_query(
                "SELECT ticker, date, adj_close FROM daily_prices ORDER BY ticker, date", conn)
            fund_df = pd.read_sql_query(
                "SELECT * FROM fundamentals WHERE period_type='Q' ORDER BY ticker, period_end", conn)
            est_df = pd.read_sql_query(
                "SELECT ticker, date, forward_eps, price_target FROM analyst_estimates "
                "ORDER BY ticker, date", conn)
            si_df = pd.read_sql_query(
                "SELECT ticker, date, shares_short, short_ratio, short_percent_float "
                "FROM short_interest ORDER BY ticker, date", conn)

        prices: dict[str, np.ndarray] = {}
        for tk, grp in prices_df.groupby("ticker"):
            prices[tk] = grp["adj_close"].to_numpy(dtype=float)
        # include sector ETFs even though they aren't in the universe
        for etf in etfs:
            if etf not in prices and etf in set(prices_df["ticker"]):
                prices[etf] = prices_df[prices_df.ticker == etf]["adj_close"].to_numpy(float)

        fund_latest_q, fund_hist_q = {}, {}
        for tk, grp in fund_df.groupby("ticker"):
            g = grp.reset_index(drop=True)
            fund_hist_q[tk] = g
            fund_latest_q[tk] = g.iloc[-1]

        estimates = {tk: g.reset_index(drop=True) for tk, g in est_df.groupby("ticker")}

        short_latest, short_prior = {}, {}
        for tk, grp in si_df.groupby("ticker"):
            g = grp.reset_index(drop=True)
            short_latest[tk] = g.iloc[-1]
            if len(g) > 1:
                short_prior[tk] = g.iloc[-2]

        asof = str(prices_df["date"].max()) if not prices_df.empty else date.today().isoformat()
        log.info("ScoringContext loaded: %d tickers, asof %s", len(tickers), asof)
        return cls(asof=asof, tickers=tickers, sector_map=sector_map, prices=prices,
                   fund_latest_q=fund_latest_q, fund_hist_q=fund_hist_q,
                   estimates=estimates, short_latest=short_latest, short_prior=short_prior)

    def last_price(self, ticker: str) -> float:
        arr = self.prices.get(ticker)
        return float(arr[-1]) if arr is not None and len(arr) else np.nan


# --- score storage ------------------------------------------------------------

PARENTS = ["momentum", "value", "quality", "growth", "revisions",
           "short_interest", "insider", "institutional"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scores (
    asof_date TEXT, ticker TEXT, sector TEXT,
    momentum REAL, value REAL, quality REAL, growth REAL, revisions REAL,
    short_interest REAL, insider REAL, institutional REAL, composite REAL,
    piotroski INTEGER, altman_z REAL,
    PRIMARY KEY (asof_date, ticker)
);
CREATE TABLE IF NOT EXISTS subfactor_scores (
    asof_date TEXT, ticker TEXT, factor TEXT, subfactor TEXT, score REAL,
    PRIMARY KEY (asof_date, ticker, factor, subfactor)
);
"""


def store_scores(asof: str, scores_df: pd.DataFrame) -> None:
    """scores_df indexed by ticker with columns: sector, the 8 parents, composite,
    piotroski, altman_z."""
    ensure_tables(_SCHEMA)
    cols = ["sector"] + PARENTS + ["composite", "piotroski", "altman_z"]
    with get_conn() as conn:
        conn.execute("DELETE FROM scores WHERE asof_date=?", (asof,))
        rows = []
        for tk, r in scores_df.iterrows():
            vals = [None if pd.isna(r.get(c)) else r.get(c) for c in cols]
            rows.append([asof, tk] + vals)
        conn.executemany(
            f"INSERT INTO scores (asof_date, ticker, {','.join(cols)}) "
            f"VALUES ({','.join('?' * (len(cols) + 2))})", rows,
        )


def store_subfactors(asof: str, factor: str, subscores: pd.DataFrame) -> None:
    ensure_tables(_SCHEMA)
    with get_conn() as conn:
        conn.execute("DELETE FROM subfactor_scores WHERE asof_date=? AND factor=?", (asof, factor))
        rows = [
            (asof, tk, factor, sub, None if pd.isna(v) else float(v))
            for tk, r in subscores.iterrows()
            for sub, v in r.items()
        ]
        conn.executemany(
            "INSERT INTO subfactor_scores (asof_date,ticker,factor,subfactor,score) "
            "VALUES (?,?,?,?,?)", rows,
        )
