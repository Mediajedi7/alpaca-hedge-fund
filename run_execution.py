#!/usr/bin/env python3
"""Layer 6 entry point — execution.

Usage:
  python3 run_execution.py --dry-run                 # log what would happen
  python3 run_execution.py --execute                 # place orders (paper)
  python3 run_execution.py --execute --max-orders 2  # capped live test
"""
from __future__ import annotations

import argparse
import json

from core.log import get_logger
from execution import executor

log = get_logger("run_execution")


def main() -> None:
    ap = argparse.ArgumentParser(description="Mediajedi Layer 6 execution")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--execute", action="store_true")
    ap.add_argument("--max-orders", type=int, default=None)
    args = ap.parse_args()

    summary = executor.run(dry_run=not args.execute, max_orders=args.max_orders)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
