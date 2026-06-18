"""Value — 6 sub-factors. Sector-percentile ranked (EV/EBITDA inverted)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from factors.base import ScoringContext, sector_percentile


def _ttm(hist: pd.DataFrame, col: str) -> float:
    """Trailing-twelve-month sum of the last 4 quarterly values of `col`."""
    if hist is None or col not in hist or len(hist) < 4:
        return np.nan
    vals = hist[col].tail(4)
    return float(vals.sum()) if vals.notna().all() else np.nan


def compute(ctx: ScoringContext) -> pd.DataFrame:
    fey, btp, fcfy, ev_ebitda, shy, sev = {}, {}, {}, {}, {}, {}
    for t in ctx.tickers:
        f = ctx.fund_latest_q.get(t)
        hist = ctx.fund_hist_q.get(t)
        price = ctx.last_price(t)
        mktcap = float(f["market_cap"]) if (f is not None and pd.notna(f.get("market_cap"))) else np.nan
        ev = float(f["enterprise_value"]) if (f is not None and pd.notna(f.get("enterprise_value"))) else np.nan

        # forward earnings yield = forward EPS / price
        est = ctx.estimates.get(t)
        fwd_eps = float(est.iloc[-1]["forward_eps"]) if (est is not None and pd.notna(est.iloc[-1]["forward_eps"])) else np.nan
        fey[t] = (fwd_eps / price) if (price and not np.isnan(price) and not np.isnan(fwd_eps)) else np.nan

        # book-to-price = equity / market cap
        if f is not None and pd.notna(f.get("total_equity")) and mktcap and not np.isnan(mktcap):
            btp[t] = float(f["total_equity"]) / mktcap

        # FCF yield (already TTM-based in fundamentals)
        if f is not None and pd.notna(f.get("fcf_yield")):
            fcfy[t] = float(f["fcf_yield"])

        ttm_ebitda = _ttm(hist, "ebitda")
        ttm_rev = _ttm(hist, "revenue")
        ttm_buybacks = _ttm(hist, "buybacks")
        ttm_divs = _ttm(hist, "dividends_paid")

        if not np.isnan(ev) and not np.isnan(ttm_ebitda) and ttm_ebitda != 0:
            ev_ebitda[t] = ev / ttm_ebitda
        if not np.isnan(mktcap) and mktcap and not np.isnan(ttm_buybacks) and not np.isnan(ttm_divs):
            shy[t] = (ttm_buybacks + ttm_divs) / mktcap
        if not np.isnan(ev) and ev and not np.isnan(ttm_rev):
            sev[t] = ttm_rev / ev

    sm = ctx.sector_map
    return pd.DataFrame({
        "fwd_earnings_yield": sector_percentile(pd.Series(fey), sm, True),
        "book_to_price": sector_percentile(pd.Series(btp), sm, True),
        "fcf_yield": sector_percentile(pd.Series(fcfy), sm, True),
        "ev_ebitda_inv": sector_percentile(pd.Series(ev_ebitda), sm, False),  # lower EV/EBITDA = cheaper
        "shareholder_yield": sector_percentile(pd.Series(shy), sm, True),
        "sales_to_ev": sector_percentile(pd.Series(sev), sm, True),
    })
