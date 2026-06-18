"""Short Interest — 3 sub-factors. Scored from the LONG perspective (low / declining
short interest = high score). In the single composite ranking this means crowded /
rising-short names sink to the bottom, where they become SHORT candidates."""
from __future__ import annotations

import numpy as np
import pandas as pd

from factors.base import ScoringContext, sector_percentile


def compute(ctx: ScoringContext) -> pd.DataFrame:
    spf, dtc, change = {}, {}, {}
    for t in ctx.tickers:
        cur = ctx.short_latest.get(t)
        if cur is None:
            continue
        spf[t] = cur.get("short_percent_float")
        dtc[t] = cur.get("short_ratio")
        prior = ctx.short_prior.get(t)
        if prior is not None and pd.notna(cur.get("shares_short")) and pd.notna(prior.get("shares_short")):
            change[t] = float(cur["shares_short"]) - float(prior["shares_short"])
        else:
            change[t] = np.nan

    sm = ctx.sector_map
    return pd.DataFrame({
        "short_pct_float_inv": sector_percentile(pd.Series(spf), sm, False),  # low short% = better (long)
        "days_to_cover_inv": sector_percentile(pd.Series(dtc), sm, False),    # low DTC = better (long)
        "short_change_inv": sector_percentile(pd.Series(change), sm, False),  # declining SI = better (long)
    })
