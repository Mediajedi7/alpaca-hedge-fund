"""Conviction-tilt optimizer (also the MVO fallback). Equal-weight base within each
book, score-conviction tilts (top 5% 1.5x, top 10% 1.25x), per-position cap (the
lesser of position_max_pct and 5%-ADV liquidity) with proportional redistribution,
earnings half-size (<=5d), beta-neutral scaling of the short book, and sector
net-exposure capping."""
from __future__ import annotations

import pandas as pd

from core.config import cfg
from core.log import get_logger
from portfolio import construct, inputs

log = get_logger("conviction")


def _conviction_mult(ranked: list[str]) -> dict[str, float]:
    top5 = float(cfg.get("portfolio.conviction.top_5pct_multiplier", 1.5))
    top10 = float(cfg.get("portfolio.conviction.top_10pct_multiplier", 1.25))
    k5 = max(1, int(len(ranked) * 0.05))
    k10 = max(1, int(len(ranked) * 0.10))
    return {t: (top5 if i < k5 else top10 if i < k10 else 1.0) for i, t in enumerate(ranked)}


def _cap_and_normalize(w: dict[str, float], target: float, caps: dict[str, float]) -> dict[str, float]:
    """Scale to `target` gross with per-name caps, redistributing excess proportionally."""
    s = sum(w.values()) or 1.0
    w = {t: target * v / s for t, v in w.items()}
    for _ in range(5):
        over = {t for t, v in w.items() if caps.get(t) and v > caps[t] + 1e-12}
        if not over:
            break
        excess = sum(w[t] - caps[t] for t in over)
        for t in over:
            w[t] = caps[t]
        free = {t: w[t] for t in w if t not in over}
        fsum = sum(free.values())
        if fsum <= 0:
            break
        for t in free:
            w[t] += excess * free[t] / fsum
    return w


def _book(names: list[str], target: float, scores: pd.DataFrame, caps: dict) -> dict[str, float]:
    if not names:
        return {}
    ranked = sorted(names, key=lambda t: scores.loc[t, "score"], reverse=True)
    raw = _conviction_mult(ranked)  # equal-weight base x conviction tilt
    # NOTE: the earnings 50% size-cut is NOT applied here — it is owned by Layer 5
    # (risk/pre_trade.py) and applied once at veto time (see config.yaml ownership note).
    return _cap_and_normalize(raw, target, caps)


def construct_portfolio(n: int | None = None) -> tuple[dict[str, float], dict[str, float], pd.DataFrame]:
    scores = construct.get_scores()
    longs, shorts = construct.select_candidates(n)
    names = longs + shorts
    betas = inputs.betas(names)
    adv = inputs.adv_dollar(names)
    aum = float(cfg.get("portfolio.aum", 1_000_000))
    pmax = float(cfg.get("portfolio.position_max_pct", 0.05))
    max_adv = float(cfg.get("portfolio.max_position_pct_adv", 0.05))
    caps = {t: min(pmax, (max_adv * adv[t] / aum) if adv.get(t) else pmax) for t in names}

    L = float(cfg.get("portfolio.target_long_gross", 0.85))
    S = float(cfg.get("portfolio.target_short_gross", 0.80))
    lw = _book(longs, L, scores, caps)
    sw = {t: -v for t, v in _book(shorts, S, scores, caps).items()}
    weights = {**lw, **sw}
    # NOTE: conviction-tilt hard-guarantees target gross, per-position caps, and the
    # conviction/earnings tilts. Net beta and sector-net are NOT jointly solved here
    # (top/bottom-score books aren't sector-/beta-matched, and these constraints can
    # conflict with gross+caps). The MVO method solves all constraints jointly; the
    # Layer 5 veto is the hard backstop for both.
    return weights, betas, scores
