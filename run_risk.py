#!/usr/bin/env python3
"""Layer 5 entry point — risk management.

Usage:
  python3 run_risk.py --report          # factor-risk decomposition + veto screen of target
  python3 run_risk.py --clear-halt      # remove the kill-switch lock
  python3 run_risk.py --record-nav 1010000
  python3 run_risk.py --check-breakers --nav 980000 --day-open 1000000 --week-open 1010000
"""
from __future__ import annotations

import argparse
import json

from core.db import get_conn
from core.log import get_logger
from risk import circuit_breakers as cb
from risk.factor_risk_model import FactorRiskModel
from risk.pre_trade import screen_target

log = get_logger("run_risk")


def _load_target():
    with get_conn() as conn:
        asof = conn.execute("SELECT MAX(asof_date) d FROM target_portfolio").fetchone()["d"]
        rows = conn.execute(
            "SELECT ticker, weight, beta, sector FROM target_portfolio WHERE asof_date=?",
            (asof,)).fetchall()
    weights = {r["ticker"]: r["weight"] for r in rows}
    betas = {r["ticker"]: (r["beta"] if r["beta"] is not None else 1.0) for r in rows}
    sectors = {r["ticker"]: r["sector"] for r in rows}
    return weights, betas, sectors


def _report() -> None:
    weights, betas, sectors = _load_target()
    if not weights:
        print("No target portfolio — run Layer 4 first.")
        return
    frm = FactorRiskModel().fit()
    dec = frm.decompose(weights)
    print("=== Factor risk decomposition ===")
    print(json.dumps({k: v for k, v in dec.items() if k != "mctr_pct"}, indent=2))

    screen = screen_target(weights, betas, sectors)
    print("\n=== Pre-trade veto screen ===")
    print(f"approved: {len(screen['approved'])}/{len(weights)}")
    print("aggregate:", json.dumps(screen["aggregate"]))
    for t, reasons in screen["rejections"].items():
        print(f"  REJECT {t}: {'; '.join(reasons)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Mediajedi Layer 5 risk management")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--clear-halt", action="store_true")
    ap.add_argument("--record-nav", type=float, default=None)
    ap.add_argument("--check-breakers", action="store_true")
    ap.add_argument("--nav", type=float)
    ap.add_argument("--day-open", type=float)
    ap.add_argument("--week-open", type=float)
    ap.add_argument("--peak", type=float, default=None)
    args = ap.parse_args()

    if args.clear_halt:
        print("Halt cleared" if cb.clear_halt() else "No halt lock present")
    if args.record_nav is not None:
        cb.record_nav(args.record_nav)
        print(f"Recorded NAV {args.record_nav}")
    if args.check_breakers:
        snap = cb.AccountSnapshot(nav=args.nav, day_open_nav=args.day_open,
                                  week_open_nav=args.week_open, peak=args.peak)
        print(json.dumps(cb.evaluate(snap), indent=2))
    if args.report:
        _report()


if __name__ == "__main__":
    main()
