"""Per-ticker transaction cost in bps: commission (0, Alpaca) + spread (5% of avg
daily high-low range) + market impact (coef·√(trade_size/ADV)·daily_vol_bps).

Returned as a fraction of notional so the MVO objective can subtract it from each
name's gross expected return. Trade size is referenced to a representative position
(position_max_pct × AUM) to keep the cost vector independent of the weights being solved."""
from __future__ import annotations

import math

from core.config import cfg
from core.log import get_logger
from portfolio import inputs

log = get_logger("transaction_costs")


def estimate(tickers: list[str], aum: float | None = None,
             ref_weight: float | None = None) -> dict[str, dict]:
    """Return {ticker: {spread_bps, impact_bps, total_bps, total_frac}}."""
    aum = aum or float(cfg.get("portfolio.aum", 1_000_000))
    ref_weight = ref_weight if ref_weight is not None else float(cfg.get("portfolio.position_max_pct", 0.05))
    commission_bps = float(cfg.get("transaction_costs.commission_bps", 0.0))
    spread_pct = float(cfg.get("transaction_costs.spread_pct_of_range", 0.05))
    coef = float(cfg.get("transaction_costs.market_impact_coef", 0.10))

    rng = inputs.avg_range_frac(tickers)
    adv = inputs.adv_dollar(tickers)
    vol = inputs.daily_vol(tickers)
    trade_notional = ref_weight * aum

    out = {}
    for t in tickers:
        spread_bps = spread_pct * (rng.get(t) or 0.0) * 10_000
        a = adv.get(t)
        v = vol.get(t)
        if a and a > 0 and v and not math.isnan(v):
            participation = trade_notional / a
            impact_bps = coef * math.sqrt(participation) * (v * 10_000)
        else:
            impact_bps = 0.0
        total_bps = commission_bps + spread_bps + impact_bps
        out[t] = {"spread_bps": round(spread_bps, 2), "impact_bps": round(impact_bps, 2),
                  "total_bps": round(total_bps, 2), "total_frac": total_bps / 10_000}
    return out


def cost_vector(tickers: list[str], aum: float | None = None) -> dict[str, float]:
    """Just the total cost fraction per ticker (for the MVO objective)."""
    return {t: d["total_frac"] for t, d in estimate(tickers, aum).items()}
