"""Diagnose whether a beta-neutral book is achievable by reweighting, for the current
candidate pool vs a wider one. Solves an LP for the minimum achievable |net beta|."""
import numpy as np
from scipy.optimize import linprog

from core.config import cfg
from portfolio import construct, inputs

L = float(cfg.get("portfolio.target_long_gross", 0.85))
S = float(cfg.get("portfolio.target_short_gross", 0.80))
pmax = float(cfg.get("portfolio.position_max_pct", 0.05))
beta_cap = float(cfg.get("portfolio.mvo.portfolio_beta_cap", 0.15))


def min_abs_net_beta(longs, shorts, floor):
    names = longs + shorts
    betas = inputs.betas(names)
    b = np.array([betas.get(t, 1.0) for t in names])
    nL, nS = len(longs), len(shorts)
    n = nL + nS
    # vars: w[0..n-1], t   ; minimize t
    c = np.zeros(n + 1); c[-1] = 1.0
    # |w.b| <= t  ->  w.b - t <= 0 ; -w.b - t <= 0
    A_ub = np.vstack([np.concatenate([b, [-1.0]]), np.concatenate([-b, [-1.0]])])
    b_ub = np.array([0.0, 0.0])
    # sum long = L ; sum short = -S
    eqL = np.zeros(n + 1); eqL[:nL] = 1.0
    eqS = np.zeros(n + 1); eqS[nL:n] = 1.0
    A_eq = np.vstack([eqL, eqS]); b_eq = np.array([L, -S])
    bounds = [(floor, pmax)] * nL + [(-pmax, -floor)] * nS + [(0, None)]
    r = linprog(c, A_ub, b_ub, A_eq, b_eq, bounds=bounds, method="highs")
    return r.fun if r.success else None, b, nL, nS


def report(label, longs, shorts, floor):
    val, b, nL, nS = min_abs_net_beta(longs, shorts, floor)
    bl = b[:nL]; bs = b[nL:]
    print(f"\n[{label}] pool={nL}L/{nS}S  floor={floor}")
    print(f"  long  beta: mean={bl.mean():.2f} min={bl.min():.2f} max={bl.max():.2f}")
    print(f"  short beta: mean={bs.mean():.2f} min={bs.min():.2f} max={bs.max():.2f}")
    if val is None:
        print("  min achievable |net beta|: INFEASIBLE")
    else:
        print(f"  min achievable |net beta|: {val:.3f}   "
              f"({'OK <= ' if val <= beta_cap else 'STILL OVER '}{beta_cap})")


# current: top/bottom 20, floor 0.005 (as MVO uses today)
l20, s20 = construct.select_candidates(20)
report("current 20/20, floor 0.5%", l20, s20, 0.005)
report("current 20/20, floor 0",   l20, s20, 0.0)

# wider pools, floor 0 (optimizer may exclude names)
for k in (30, 40, 60):
    lk, sk = construct.select_candidates(k)
    report(f"wider {k}/{k}, floor 0", lk, sk, 0.0)
