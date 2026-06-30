"""Reset the fund's performance track record — for a clean restart (e.g. moving to a
fresh or LIVE Alpaca account). Clears ONLY track-record/history state and PRESERVES all
model state (scores, subfactor_scores, combined_scores, target_portfolio, analysis_results,
prices, fundamentals, universe, SEC/insider/13-F data, estimates, earnings calendar).

Guarded: DRY-RUN by default, backs up the DB before deleting, and requires --confirm AND a
typed phrase to actually wipe. Does NOT edit config.yaml (it is hand-edited to preserve the
inline comments) — instead it prints the exact fund.* lines to update.

  python3 -m scripts.reset_track_record                                  # dry-run (default)
  python3 -m scripts.reset_track_record --confirm                        # backup + wipe (prompts)
  python3 -m scripts.reset_track_record --starting-capital 250000 --inception 2026-09-01
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from core.config import ROOT
from core.db import DB_PATH, get_conn

CONFIRM_PHRASE = "RESET TRACK RECORD"
# Performance / history only. Everything NOT in this list (model + market data) is preserved.
TRACK_TABLES = ["cash_flows", "equity_curve", "orders", "lp_letters",
                "jarvis_commentary", "veto_rejections"]
ATTR_CSV = ROOT / "output" / "daily_attribution.csv"


def _counts() -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    with get_conn() as c:
        for t in TRACK_TABLES:
            try:
                out[t] = c.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
            except sqlite3.Error:
                out[t] = None  # table not created yet
    return out


def _backup_db() -> Path:
    bdir = ROOT / "cache" / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    dest = bdir / f"meridian-pre-reset-{datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(DB_PATH, timeout=30.0)          # WAL-safe consistent snapshot
    try:
        dst = sqlite3.connect(dest)
        with dst:
            src.backup(dst)
        dst.close()
    finally:
        src.close()
    return dest


def _print_config_reminder(args) -> None:
    sc = args.starting_capital if args.starting_capital is not None else "<new opening equity>"
    inc = args.inception or "<YYYY-MM-DD start>"
    print("\nManual config step — edit config.yaml (kept hand-edited to preserve comments):")
    print(f"  fund.starting_capital: {sc}")
    print(f'  fund.inception: "{inc}"')


def main() -> None:
    ap = argparse.ArgumentParser(description="Reset the fund performance track record (guarded).")
    ap.add_argument("--confirm", action="store_true",
                    help="actually back up + wipe (still prompts for the typed phrase)")
    ap.add_argument("--starting-capital", type=float, help="new fund.starting_capital (printed for config)")
    ap.add_argument("--inception", help="new fund.inception YYYY-MM-DD (printed for config)")
    args = ap.parse_args()

    counts = _counts()
    print("Track-record state to CLEAR (all model/market-data tables are PRESERVED):")
    for t, n in counts.items():
        print(f"  {t:20} {'— (no table)' if n is None else f'{n} rows'}")
    print(f"  {ATTR_CSV.name:20} {'present' if ATTR_CSV.exists() else 'absent'}")

    if not args.confirm:
        print("\nDRY-RUN — nothing changed. Re-run with --confirm to back up the DB and wipe.")
        _print_config_reminder(args)
        return

    if input(f'\nType "{CONFIRM_PHRASE}" to back up + wipe the track record: ').strip() != CONFIRM_PHRASE:
        print("Phrase mismatch — aborting. Nothing changed.")
        sys.exit(1)

    backup = _backup_db()
    print(f"[reset] DB backed up -> {backup}")
    with get_conn() as c:
        for t, n in counts.items():
            if n is not None:
                c.execute(f"DELETE FROM {t}")
                print(f"[reset] cleared {t} ({n} rows)")
    if ATTR_CSV.exists():
        ATTR_CSV.unlink()
        print(f"[reset] removed {ATTR_CSV}")
    print("[reset] Track record cleared; model + market data untouched.")
    _print_config_reminder(args)


if __name__ == "__main__":
    main()
