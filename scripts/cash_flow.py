"""Log or list external cash flows (deposits / withdrawals) for accurate P&L.

  python3 -m scripts.cash_flow --withdraw 5000 --note "monthly skim"
  python3 -m scripts.cash_flow --deposit 10000 --note "added capital"
  python3 -m scripts.cash_flow --list
"""
import argparse

from reporting import pnl


def main() -> None:
    ap = argparse.ArgumentParser(description="Cash-flow ledger")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--withdraw", type=float, help="amount pulled out")
    g.add_argument("--deposit", type=float, help="amount added")
    g.add_argument("--list", action="store_true")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    if args.list or (args.withdraw is None and args.deposit is None):
        for r in pnl.history():
            print(f"{r['ts']}  {r['amount']:+,.2f}  {r['note']}")
        print(f"\nnet flows: {pnl.net_flows():+,.2f}  |  cost basis: ${pnl.cost_basis():,.2f}")
        return

    amount = -abs(args.withdraw) if args.withdraw is not None else abs(args.deposit)
    pnl.record(amount, args.note)
    print(f"recorded {amount:+,.2f} ({args.note or 'no note'}); net flows now {pnl.net_flows():+,.2f}")


if __name__ == "__main__":
    main()
