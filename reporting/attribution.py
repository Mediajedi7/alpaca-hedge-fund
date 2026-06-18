"""P&L attribution and sector-relative alpha. daily_return = beta + sector + factor +
alpha_residual, persisted to output/daily_attribution.csv. Uses the current target
book as the position proxy (a daily positions snapshot would refine this later)."""
from __future__ import annotations

from datetime import date

import pandas as pd

from core.config import ROOT
from core.db import get_conn
from core.log import get_logger
from factors.base import SECTOR_ETF

log = get_logger("attribution")

ATTR_CSV = ROOT / "output" / "daily_attribution.csv"


def _book() -> pd.DataFrame:
    with get_conn() as conn:
        asof = conn.execute("SELECT MAX(asof_date) d FROM target_portfolio").fetchone()["d"]
        df = pd.read_sql_query(
            "SELECT ticker, weight, beta, sector FROM target_portfolio WHERE asof_date=?",
            conn, params=(asof,))
    return df


def _last_return(ticker: str) -> float | None:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT adj_close FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT 2",
            (ticker,)).fetchall()
    if len(rows) < 2 or not rows[1]["adj_close"]:
        return None
    return rows[0]["adj_close"] / rows[1]["adj_close"] - 1.0


def daily_attribution(persist: bool = True) -> dict:
    book = _book()
    if book.empty:
        return {}
    spy = _last_return("SPY") or 0.0
    net_beta = float((book["weight"] * book["beta"].fillna(1.0)).sum())

    port_ret, sector_comp = 0.0, 0.0
    for r in book.itertuples():
        ri = _last_return(r.ticker)
        if ri is None:
            continue
        port_ret += r.weight * ri
        etf = SECTOR_ETF.get(r.sector)
        etf_ret = _last_return(etf) if etf else None
        if etf_ret is not None:
            sector_comp += r.weight * (etf_ret - spy)  # sector tilt beyond market

    beta_comp = net_beta * spy
    factor_comp = 0.0  # reserved for factor-return regression once a daily series exists
    alpha = port_ret - beta_comp - sector_comp - factor_comp
    row = {"date": date.today().isoformat(), "portfolio_return": round(port_ret, 6),
           "beta": round(beta_comp, 6), "sector": round(sector_comp, 6),
           "factor": round(factor_comp, 6), "alpha_residual": round(alpha, 6)}

    if persist:
        ATTR_CSV.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame([row])
        header = not ATTR_CSV.exists()
        df.to_csv(ATTR_CSV, mode="a", header=header, index=False)
        log.info("Attribution appended: %s", row)
    return row


def sector_relative_alpha(days: int = 90) -> dict:
    """Per sector: avg holding return vs sector-ETF return over `days` = selection alpha."""
    book = _book()
    if book.empty:
        return {"sectors": {}, "total_alpha": 0.0, "winners": 0, "losers": 0}

    def ret_n(ticker):
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT adj_close FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT ?",
                (ticker, days)).fetchall()
        if len(rows) < 2 or not rows[-1]["adj_close"]:
            return None
        return rows[0]["adj_close"] / rows[-1]["adj_close"] - 1.0

    sectors, winners, losers, total = {}, 0, 0, 0.0
    for sec, grp in book.groupby("sector"):
        etf = SECTOR_ETF.get(sec)
        etf_ret = ret_n(etf) if etf else None
        if etf_ret is None:
            continue
        picks = [ret_n(t) * (1 if w > 0 else -1) for t, w in zip(grp.ticker, grp.weight)
                 if ret_n(t) is not None]
        if not picks:
            continue
        sel = sum(picks) / len(picks) - etf_ret
        sectors[sec] = round(sel, 4)
        total += sel
        winners += sel > 0
        losers += sel < 0
    return {"sectors": sectors, "total_alpha": round(total, 4), "winners": winners, "losers": losers}
