"""Performance metrics from the equity_curve table: NAV series, daily returns,
Sharpe, drawdown, monthly grid, and rebased equity-vs-SPY. Degrades gracefully
when history is short (the fund is new)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.db import ensure_tables, get_conn

_EC = "CREATE TABLE IF NOT EXISTS equity_curve (ts TEXT PRIMARY KEY, nav REAL);"


def equity_series() -> pd.Series:
    ensure_tables(_EC)
    with get_conn() as conn:
        df = pd.read_sql_query("SELECT ts, nav FROM equity_curve ORDER BY ts", conn)
    if df.empty:
        return pd.Series(dtype=float)
    s = pd.Series(df["nav"].values, index=pd.to_datetime(df["ts"]))
    return s


def daily_nav() -> pd.Series:
    s = equity_series()
    return s.resample("1D").last().dropna() if not s.empty else s


def returns() -> pd.Series:
    nav = daily_nav()
    return nav.pct_change().dropna() if len(nav) > 1 else pd.Series(dtype=float)


def sharpe(rets: pd.Series, periods: int = 252) -> float | None:
    if len(rets) < 2 or rets.std() == 0:
        return None
    return float(rets.mean() / rets.std() * np.sqrt(periods))


def drawdown() -> tuple[pd.Series, float]:
    nav = daily_nav()
    if nav.empty:
        return pd.Series(dtype=float), 0.0
    peak = nav.cummax()
    dd = nav / peak - 1.0
    return dd, float(dd.min())


def monthly_returns() -> pd.DataFrame:
    nav = daily_nav()
    if len(nav) < 2:
        return pd.DataFrame()
    m = nav.resample("ME").last().pct_change().dropna()
    if m.empty:
        return pd.DataFrame()
    df = m.to_frame("ret")
    df["year"] = df.index.year
    df["month"] = df.index.month
    return df.pivot_table(index="year", columns="month", values="ret")


def spy_rebased(start) -> pd.Series:
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT date, adj_close FROM daily_prices WHERE ticker='SPY' AND date>=? ORDER BY date",
            conn, params=(str(start),))
    if df.empty:
        return pd.Series(dtype=float)
    s = pd.Series(df["adj_close"].values, index=pd.to_datetime(df["date"]))
    return s / s.iloc[0] * 100.0


def summary() -> dict:
    nav = daily_nav()
    rets = returns()
    _, maxdd = drawdown()
    if nav.empty:
        return {"history_days": 0}
    total_ret = float(nav.iloc[-1] / nav.iloc[0] - 1.0) if len(nav) > 1 else 0.0
    return {
        "history_days": len(nav),
        "nav": round(float(nav.iloc[-1]), 2),
        "total_return": round(total_ret, 4),
        "ann_vol": round(float(rets.std() * np.sqrt(252)), 4) if len(rets) > 1 else None,
        "sharpe": round(sharpe(rets), 2) if sharpe(rets) is not None else None,
        "max_drawdown": round(maxdd, 4),
    }
