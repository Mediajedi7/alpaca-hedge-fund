"""Preflight + arming for switching to a LIVE Alpaca account.

Read-only by default: it CHECKS every prerequisite and prints a go/no-go. It never places
trades. With --arm it will, only if all critical checks pass and you type the phrase, write
the LIVE_ARMED.lock so the non-interactive cron auto-executor can trade live.

This does NOT flip `fund.mode` (config.yaml is hand-edited) — it tells you to. The full
procedure is the 'Live cutover checklist' in CLAUDE.md.

  python3 -m scripts.go_live            # preflight only (read-only)
  python3 -m scripts.go_live --arm      # if all pass: prompt + write cache/LIVE_ARMED.lock
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.config import ROOT, cfg, env
from execution.broker import LIVE_CONFIRMATION
from reporting import pnl

LOCK = Path(ROOT / cfg.get("execution.live_arm_lock", "cache/LIVE_ARMED.lock"))


def _check(label: str, ok: bool, detail: str) -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {detail}")
    return ok


def _sip_ok() -> tuple[bool, str]:
    """Verify a SIP entitlement by requesting one SIP quote with the LIVE keys."""
    key, secret = env("ALPACA_LIVE_API_KEY"), env("ALPACA_LIVE_SECRET_KEY")
    if not (key and secret):
        return False, "no live keys to test SIP with"
    try:
        from alpaca.data.enums import DataFeed
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestQuoteRequest
        c = StockHistoricalDataClient(key, secret)
        c.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=["AAPL"], feed=DataFeed.SIP))
        return True, "SIP quote returned"
    except Exception as e:  # noqa: BLE001
        return False, f"SIP request failed ({type(e).__name__}: {e})"


def main() -> None:
    ap = argparse.ArgumentParser(description="Live-cutover preflight + arming (guarded).")
    ap.add_argument("--arm", action="store_true",
                    help="if all critical checks pass, prompt for the phrase and write LIVE_ARMED.lock")
    args = ap.parse_args()

    print("LIVE cutover preflight\n----------------------")
    live_keys = bool(env("ALPACA_LIVE_API_KEY") and env("ALPACA_LIVE_SECRET_KEY"))
    sip, sip_detail = _sip_ok()
    feed = str(cfg.get("execution.data_feed", "") or "").lower()
    mode = str(cfg.get("fund.mode", "paper")).lower()

    c1 = _check("live API keys", live_keys, "ALPACA_LIVE_API_KEY/SECRET present" if live_keys
                else "set ALPACA_LIVE_API_KEY + ALPACA_LIVE_SECRET_KEY in .env")
    c2 = _check("SIP data feed entitlement", sip, sip_detail)
    c3 = _check("execution.data_feed = sip", feed == "sip",
                f"currently '{feed or 'iex (default)'}' — set execution.data_feed: sip in config.yaml")
    # advisory (not blocking the arm, but you almost always want a clean record on a new account)
    flows = 0
    try:
        flows = len(pnl.history(limit=1))
    except Exception:  # noqa: BLE001
        pass
    _check("track record reset", flows == 0,
           "clean" if flows == 0 else "non-empty — run `python3 -m scripts.reset_track_record` first (advisory)")
    _check("fund.mode = live", mode == "live",
           "live" if mode == "live" else "still 'paper' — set fund.mode: live in config.yaml (do this last)")

    critical = c1 and c2 and c3
    print("\n" + ("ALL CRITICAL CHECKS PASS." if critical else "NOT READY — resolve FAIL items above."))

    if not args.arm:
        print("Preflight only (read-only). Re-run with --arm to write the live lock once ready.")
        return
    if not critical:
        print("Refusing to arm: critical checks failed."); sys.exit(1)
    if input(f'\nType "{LIVE_CONFIRMATION}" to ARM live trading: ').strip() != LIVE_CONFIRMATION:
        print("Phrase mismatch — not armed."); sys.exit(1)
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(LIVE_CONFIRMATION + "\n")
    print(f"[go_live] ARMED — wrote {LOCK}. The cron auto-executor can now trade LIVE.")
    print("[go_live] Disarm any time: delete that file (and/or set fund.mode: paper).")


if __name__ == "__main__":
    main()
