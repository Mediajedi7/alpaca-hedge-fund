#!/usr/bin/env python3
"""Layer 4 entry point — portfolio construction.

Usage:
  python3 run_portfolio.py --optimize-method mvo
  python3 run_portfolio.py --optimize-method conviction
"""
from __future__ import annotations

import argparse
import json

from core.config import cfg
from core.log import get_logger
from portfolio import construct, mvo_optimizer
from portfolio import optimizer as conviction

log = get_logger("run_portfolio")


def main() -> None:
    ap = argparse.ArgumentParser(description="Mediajedi Layer 4 portfolio construction")
    ap.add_argument("--optimize-method", choices=["mvo", "conviction"],
                    default=cfg.get("portfolio.optimize_method", "conviction"))
    ap.add_argument("--n", type=int, default=None, help="candidates per side")
    args = ap.parse_args()

    if args.optimize_method == "mvo":
        weights, betas, scores, used = mvo_optimizer.optimize(args.n)
    else:
        weights, betas, scores = conviction.construct_portfolio(args.n)
        used = "conviction"

    construct.store_target(used, weights, betas, scores)
    summ = construct.summary(weights, betas, scores)
    log.info("Portfolio (%s): %s", used, json.dumps(summ))

    ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    print(f"\n=== Target portfolio (method={used}) ===")
    print(json.dumps(summ, indent=2))
    print("\nTop 5 longs:")
    for t, w in ranked[:5]:
        print(f"  {t:6s} {w:+.3%}  beta={betas.get(t, 1.0):.2f}  sector={scores.loc[t, 'sector'] if t in scores.index else '?'}")
    print("Top 5 shorts:")
    for t, w in ranked[-5:]:
        print(f"  {t:6s} {w:+.3%}  beta={betas.get(t, 1.0):.2f}  sector={scores.loc[t, 'sector'] if t in scores.index else '?'}")


if __name__ == "__main__":
    main()
