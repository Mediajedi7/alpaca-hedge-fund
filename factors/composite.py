"""Composite scorer — runs all 8 factor modules, equal-weights sub-factors into
parent scores, blends parents by config weights, and re-ranks the blend within
sector into the final composite (0-100)."""
from __future__ import annotations

import pandas as pd

from core.config import cfg
from core.log import get_logger
from factors import (
    growth,
    institutional,
    insider,
    momentum,
    quality,
    revisions,
    short_interest,
    value,
)
from factors.base import PARENTS, ScoringContext, combine_subfactors, sector_percentile, \
    store_scores, store_subfactors

log = get_logger("composite")


def score_all(ctx: ScoringContext, persist: bool = True) -> pd.DataFrame:
    # Each module returns sub-factor scores (already sector-percentiled)
    subscores = {
        "momentum": momentum.compute(ctx),
        "value": value.compute(ctx),
        "growth": growth.compute(ctx),
        "revisions": revisions.compute(ctx),
        "short_interest": short_interest.compute(ctx),
        "insider": insider.compute(ctx),
        "institutional": institutional.compute(ctx),
    }
    quality_sub, quality_extra = quality.compute(ctx)
    subscores["quality"] = quality_sub

    # Parent scores = equal-weight sub-factors, re-ranked within sector
    parents = pd.DataFrame(index=ctx.tickers)
    for name, sub in subscores.items():
        parents[name] = combine_subfactors(sub, ctx.sector_map)

    # Composite = config-weighted blend of parents, re-ranked within sector
    weights = cfg.get("factors.weights", {})
    wsum = sum(weights.get(p, 0) for p in PARENTS) or 1.0
    blend = sum(parents[p] * weights.get(p, 0) for p in PARENTS) / wsum
    composite = sector_percentile(blend, ctx.sector_map, True)

    out = parents.copy()
    out["sector"] = pd.Series(ctx.sector_map)
    out["composite"] = composite
    out["piotroski"] = quality_extra["piotroski"]
    out["altman_z"] = quality_extra["altman_z"]

    if persist:
        store_scores(ctx.asof, out)
        for name, sub in subscores.items():
            store_subfactors(ctx.asof, name, sub)
        log.info("Scored %d tickers, stored asof %s", len(out), ctx.asof)
    return out
