"""Mean-variance optimizer: maximize μᵀw − λ·wᵀΣw via scipy SLSQP. Long/short sets
are fixed from scores (sign enforced by bounds). Covariance comes from a pluggable
CovarianceProvider (120-day historical now; Layer 5 factor-cov later). Falls back to
the conviction-tilt optimizer if SLSQP does not converge."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from core.config import cfg
from core.log import get_logger
from portfolio import construct, inputs, optimizer as conviction, transaction_costs
from portfolio.covariance import CovarianceProvider, HistoricalCovarianceProvider

log = get_logger("mvo")


def optimize(n: int | None = None, cov_provider: CovarianceProvider | None = None
             ) -> tuple[dict[str, float], dict[str, float], pd.DataFrame, str]:
    scores = construct.get_scores()
    longs, shorts = construct.select_candidates(n)
    cov_provider = cov_provider or HistoricalCovarianceProvider()

    try:
        Sigma_all, ordered = cov_provider.cov(longs + shorts)
    except ValueError as e:
        log.warning("covariance unavailable (%s) — using conviction-tilt fallback", e)
        w, b, s = conviction.construct_portfolio(n)
        return w, b, s, "conviction(fallback)"

    longs = [t for t in longs if t in ordered]
    shorts = [t for t in shorts if t in ordered]
    names = longs + shorts
    posmap = {t: ordered.index(t) for t in names}
    pos = [posmap[t] for t in names]
    Sigma = Sigma_all[np.ix_(pos, pos)]
    nn = len(names)
    sign = np.array([1.0] * len(longs) + [-1.0] * len(shorts))

    betas = inputs.betas(names)
    beta = np.array([betas.get(t, 1.0) for t in names])
    cost = transaction_costs.cost_vector(names)
    mu = np.array([construct.expected_return(scores.loc[t, "score"]) for t in names])
    mu_eff = mu - sign * np.array([cost.get(t, 0.0) for t in names])  # net of trading cost

    lam = float(cfg.get("portfolio.mvo.risk_aversion_lambda", 1.0))
    L = float(cfg.get("portfolio.target_long_gross", 0.85))
    S = float(cfg.get("portfolio.target_short_gross", 0.80))
    pmin = float(cfg.get("portfolio.position_min_pct", 0.005))
    pmax = float(cfg.get("portfolio.position_max_pct", 0.05))
    beta_cap = float(cfg.get("portfolio.mvo.portfolio_beta_cap", 0.15))
    sec_net = float(cfg.get("portfolio.mvo.sector_net_max", 0.05))
    sec_side = float(cfg.get("portfolio.mvo.sector_single_side_max", 0.25))

    li = np.arange(len(longs))
    si = np.arange(len(longs), nn)
    sectors = {t: scores.loc[t, "sector"] for t in names}
    sec_groups: dict[str, list[int]] = {}
    for i, t in enumerate(names):
        sec_groups.setdefault(sectors[t], []).append(i)

    def neg_obj(w):
        return -mu_eff @ w + lam * w @ Sigma @ w

    cons = [
        {"type": "eq", "fun": lambda w: w[li].sum() - L},
        {"type": "eq", "fun": lambda w: w[si].sum() + S},
        {"type": "ineq", "fun": lambda w: beta_cap - w @ beta},
        {"type": "ineq", "fun": lambda w: beta_cap + w @ beta},
    ]
    for sec, idxs in sec_groups.items():
        ix = np.array(idxs)
        cons.append({"type": "ineq", "fun": lambda w, ix=ix: sec_net - w[ix].sum()})
        cons.append({"type": "ineq", "fun": lambda w, ix=ix: sec_net + w[ix].sum()})
        long_ix = np.array([i for i in idxs if i < len(longs)] or [-1])
        short_ix = np.array([i for i in idxs if i >= len(longs)] or [-1])
        if long_ix[0] >= 0:
            cons.append({"type": "ineq", "fun": lambda w, ix=long_ix: sec_side - w[ix].sum()})
        if short_ix[0] >= 0:
            cons.append({"type": "ineq", "fun": lambda w, ix=short_ix: sec_side + w[ix].sum()})

    bounds = [(pmin, pmax)] * len(longs) + [(-pmax, -pmin)] * len(shorts)
    x0 = np.concatenate([np.full(len(longs), L / max(len(longs), 1)),
                         np.full(len(shorts), -S / max(len(shorts), 1))])

    res = minimize(neg_obj, x0, method="SLSQP", bounds=bounds, constraints=cons,
                   options={"maxiter": 500, "ftol": 1e-9})

    if not res.success:
        log.warning("MVO did not converge (%s) — using conviction-tilt fallback", res.message)
        w, b, s = conviction.construct_portfolio(n)
        return w, b, s, "conviction(fallback)"

    weights = {t: float(res.x[i]) for i, t in enumerate(names)}
    log.info("MVO converged: objective=%.5f", -res.fun)
    return weights, betas, scores, "mvo"
