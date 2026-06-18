"""Market-data inputs for portfolio construction, loaded from daily_prices:
daily returns, beta vs SPY, 20-day ADV ($), daily volatility, and average
high-low range. Shared by the optimizers and the transaction-cost model."""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import cfg
from core.db import get_conn

BENCHMARK = "SPY"


def _panel(tickers: list[str], field: str, lookback: int) -> pd.DataFrame:
    """date x ticker panel of `field`, last `lookback` rows."""
    uniq = sorted(set(tickers))
    qmarks = ",".join("?" * len(uniq))
    with get_conn() as conn:
        df = pd.read_sql_query(
            f"SELECT date, ticker, {field} FROM daily_prices WHERE ticker IN ({qmarks}) "
            "ORDER BY date", conn, params=uniq)
    wide = df.pivot(index="date", columns="ticker", values=field)
    return wide.tail(lookback)


def returns(tickers: list[str], lookback: int) -> pd.DataFrame:
    # +1 row so pct_change yields `lookback` returns
    px = _panel(tickers, "adj_close", lookback + 1)
    rets = px.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    return rets.dropna(how="all")


def betas(tickers: list[str], lookback: int | None = None) -> dict[str, float]:
    """Beta vs SPY = cov(stock, spy) / var(spy) over the lookback window."""
    lb = lookback or int(cfg.get("portfolio.beta_lookback_days", 252))
    rets = returns(list(tickers) + [BENCHMARK], lb)
    if BENCHMARK not in rets:
        return {t: 1.0 for t in tickers}
    spy = rets[BENCHMARK]
    var = spy.var()
    out = {}
    for t in tickers:
        if t in rets and var and not np.isnan(var):
            pair = pd.concat([rets[t], spy], axis=1).dropna()
            out[t] = float(pair.iloc[:, 0].cov(pair.iloc[:, 1]) / var) if len(pair) > 20 else 1.0
        else:
            out[t] = 1.0
    return out


def adv_dollar(tickers: list[str], days: int = 20) -> dict[str, float]:
    """20-day average daily dollar volume (close * volume)."""
    close = _panel(tickers, "close", days)
    vol = _panel(tickers, "volume", days)
    dollar = (close * vol).mean()
    return {t: float(dollar.get(t, np.nan)) for t in tickers}


def daily_vol(tickers: list[str], lookback: int = 120) -> dict[str, float]:
    rets = returns(tickers, lookback)
    sd = rets.std()
    return {t: float(sd.get(t, np.nan)) for t in tickers}


def avg_range_frac(tickers: list[str], days: int = 20) -> dict[str, float]:
    """Mean daily (high-low)/close — used for the spread-cost component."""
    hi = _panel(tickers, "high", days)
    lo = _panel(tickers, "low", days)
    cl = _panel(tickers, "close", days)
    rng = ((hi - lo) / cl).mean()
    return {t: float(rng.get(t, np.nan)) for t in tickers}
