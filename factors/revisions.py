"""Estimate Revisions — 3 sub-factors (30/60/90-day change in consensus next-Q EPS).
Degenerate (all 50) until ~30 days of estimate snapshots have accumulated."""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from core.config import cfg
from factors.base import NO_DATA, ScoringContext, sector_percentile

SUBS = ["eps_rev_30d", "eps_rev_60d", "eps_rev_90d"]


def _delta(df: pd.DataFrame, days: int) -> float:
    """Latest forward_eps minus the snapshot from ~`days` ago (nearest on/before)."""
    if df is None or len(df) < 2:
        return np.nan
    df = df.dropna(subset=["forward_eps"])
    if df.empty:
        return np.nan
    latest_date = datetime.fromisoformat(str(df.iloc[-1]["date"]))
    cutoff = (latest_date - timedelta(days=days)).date().isoformat()
    past = df[df["date"] <= cutoff]
    if past.empty:
        return np.nan
    return float(df.iloc[-1]["forward_eps"]) - float(past.iloc[-1]["forward_eps"])


def compute(ctx: ScoringContext) -> pd.DataFrame:
    # Snapshot span across all tickers
    dates = [d for g in ctx.estimates.values() for d in g["date"].tolist()]
    min_days = int(cfg.get("factors.revisions_min_snapshot_days", 30))
    span = 0
    if dates:
        span = (datetime.fromisoformat(max(dates)) - datetime.fromisoformat(min(dates))).days

    if span < min_days:
        # Not enough history -> every score is the sector median (50)
        return pd.DataFrame({s: pd.Series(NO_DATA, index=ctx.tickers) for s in SUBS})

    sm = ctx.sector_map
    cols = {}
    for days, name in ((30, "eps_rev_30d"), (60, "eps_rev_60d"), (90, "eps_rev_90d")):
        raw = {t: _delta(ctx.estimates.get(t), days) for t in ctx.tickers}
        cols[name] = sector_percentile(pd.Series(raw), sm, True)
    return pd.DataFrame(cols)
