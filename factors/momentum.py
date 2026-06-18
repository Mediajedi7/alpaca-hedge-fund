"""Momentum — 6 sub-factors (all higher = better). Sector-percentile ranked."""
from __future__ import annotations

import numpy as np
import pandas as pd

from factors.base import SECTOR_ETF, ScoringContext, _ret, _ret_between, sector_percentile

# trading-day approximations
M1, M3, M6, M12 = 21, 63, 126, 252


def compute(ctx: ScoringContext) -> pd.DataFrame:
    r12_1, r6, r3, accel, high52, rel = {}, {}, {}, {}, {}, {}
    for t in ctx.tickers:
        arr = ctx.prices.get(t)
        if arr is None or len(arr) < M3:
            continue
        r12_1[t] = _ret_between(arr, M1, M12)          # 12-1m (skip recent month)
        r6[t] = _ret(arr, M6)
        r3[t] = _ret(arr, M3)
        recent3 = _ret(arr, M3)
        older3 = _ret_between(arr, M3, M6)
        accel[t] = (recent3 - older3) if not (np.isnan(recent3) or np.isnan(older3)) else np.nan
        if len(arr) >= M12:
            hi = np.max(arr[-M12:])
            high52[t] = arr[-1] / hi if hi else np.nan
        etf = SECTOR_ETF.get(ctx.sector_map.get(t))
        etf_arr = ctx.prices.get(etf) if etf else None
        rel[t] = (r6[t] - _ret(etf_arr, M6)) if (etf_arr is not None and t in r6) else np.nan

    sm = ctx.sector_map
    return pd.DataFrame({
        "ret_12_1m": sector_percentile(pd.Series(r12_1), sm, True),
        "ret_6m": sector_percentile(pd.Series(r6), sm, True),
        "ret_3m": sector_percentile(pd.Series(r3), sm, True),
        "acceleration": sector_percentile(pd.Series(accel), sm, True),
        "high_52w_proximity": sector_percentile(pd.Series(high52), sm, True),
        "rel_strength_sector": sector_percentile(pd.Series(rel), sm, True),
    })
