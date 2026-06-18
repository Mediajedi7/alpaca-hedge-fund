"""Institutional Flow — 3 sub-factors from tracked-fund 13-F holdings. If no 13-F
data is loaded at all, the whole factor is degenerate (50)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.db import get_conn
from data.institutional import institutional_summary
from factors.base import NO_DATA, ScoringContext, sector_percentile

SUBS = ["funds_holding", "net_holdings_change", "multi_fund_open"]


def _has_any_data() -> bool:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) c FROM institutional_holdings").fetchone()["c"] > 0


def compute(ctx: ScoringContext) -> pd.DataFrame:
    if not _has_any_data():
        return pd.DataFrame({s: pd.Series(NO_DATA, index=ctx.tickers) for s in SUBS})

    funds, change, multi = {}, {}, {}
    for t in ctx.tickers:
        s = institutional_summary(t)
        funds[t] = s["num_funds_holding"]
        change[t] = s["net_share_change"]
        multi[t] = 1.0 if s["multi_fund_open"] else 0.0

    sm = ctx.sector_map
    return pd.DataFrame({
        "funds_holding": sector_percentile(pd.Series(funds), sm, True),
        "net_holdings_change": sector_percentile(pd.Series(change), sm, True),
        "multi_fund_open": sector_percentile(pd.Series(multi), sm, True),
    })
