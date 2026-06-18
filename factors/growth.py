"""Growth — 5 sub-factors (all higher = better). Sector-percentile ranked."""
from __future__ import annotations

import numpy as np
import pandas as pd

from factors.base import ScoringContext, sector_percentile


def _latest(h, c):
    return h[c].iloc[-1] if (h is not None and c in h and len(h)) else np.nan


def _ago(h, c, q=4):
    return h[c].iloc[-1 - q] if (h is not None and c in h and len(h) > q) else np.nan


def _ttm_fcf_growth(h) -> float:
    """TTM FCF now vs TTM FCF a year ago (needs >= 8 quarters)."""
    if h is None or "free_cash_flow" not in h or len(h) < 8:
        return np.nan
    now = h["free_cash_flow"].iloc[-4:].sum()
    prior = h["free_cash_flow"].iloc[-8:-4].sum()
    if not prior:
        return np.nan
    return now / abs(prior) - 1.0 if prior > 0 else np.nan


def compute(ctx: ScoringContext) -> pd.DataFrame:
    rev_yoy, eps_yoy, rev_accel, rd_int, fcf_g = {}, {}, {}, {}, {}
    for t in ctx.tickers:
        h = ctx.fund_hist_q.get(t)
        if h is None:
            continue
        rev_yoy[t] = _latest(h, "rev_growth_yoy")
        eps_yoy[t] = _latest(h, "earnings_growth_yoy")
        now, ago = _latest(h, "rev_growth_yoy"), _ago(h, "rev_growth_yoy", 4)
        rev_accel[t] = (now - ago) if (pd.notna(now) and pd.notna(ago)) else np.nan
        rd, rev = _latest(h, "rd_expense"), _latest(h, "revenue")
        rd_int[t] = (rd / rev) if (pd.notna(rd) and pd.notna(rev) and rev) else np.nan
        fcf_g[t] = _ttm_fcf_growth(h)

    sm = ctx.sector_map
    return pd.DataFrame({
        "rev_growth_yoy": sector_percentile(pd.Series(rev_yoy), sm, True),
        "earnings_growth_yoy": sector_percentile(pd.Series(eps_yoy), sm, True),
        "rev_growth_accel": sector_percentile(pd.Series(rev_accel), sm, True),
        "rd_intensity": sector_percentile(pd.Series(rd_int), sm, True),
        "fcf_growth_yoy": sector_percentile(pd.Series(fcf_g), sm, True),
    })
