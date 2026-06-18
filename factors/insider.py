"""Insider Activity — 3 sub-factors from Form 4 data (codes P/S only; A/M/F ignored
upstream). No data -> sector median (50). Uses data.sec_data.insider_summary."""
from __future__ import annotations

import numpy as np
import pandas as pd

from data.sec_data import insider_summary
from factors.base import ScoringContext, sector_percentile


def compute(ctx: ScoringContext) -> pd.DataFrame:
    net_flow, ceo_cfo, cluster = {}, {}, {}
    for t in ctx.tickers:
        s = insider_summary(t, window_days=90)
        if not s["has_data"]:
            net_flow[t] = ceo_cfo[t] = cluster[t] = np.nan   # -> 50
            continue
        net_flow[t] = s["net_dollar_flow"]
        ceo_cfo[t] = s["ceo_cfo_buy_value"]
        cluster[t] = 1.0 if s["cluster_buy"] else 0.0

    sm = ctx.sector_map
    return pd.DataFrame({
        "net_dollar_flow_90d": sector_percentile(pd.Series(net_flow), sm, True),
        "ceo_cfo_weighted_buys": sector_percentile(pd.Series(ceo_cfo), sm, True),
        "cluster_buy": sector_percentile(pd.Series(cluster), sm, True),
    })
