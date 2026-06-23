"""Monday auto-execution (option C): run the executor against the latest target book and
email a confirmation of what happened.

Guardrails (all enforced inside executor.run):
  * refuses if the kill-switch HALT.lock is set,
  * refuses if the target fails the aggregate pre-trade veto,
  * sizes every position off LIVE Alpaca equity (broker.equity()) within the veto caps
    (gross <= 165%, per-name <= 5% equity / 5% ADV, net in [-10%, +15%]).

This is the ONLY automation that opens positions. It emails either a confirmation of the
orders placed, or — if it declined to trade — the reason, so a no-trade is never silent.
"""
from __future__ import annotations

import json
from datetime import date

from core.config import cfg
from core.db import get_conn
from core.log import get_logger
from core.notify import send_email
from execution import autoexec_state, executor

log = get_logger("auto_execute")
TAG = "[Mediajedi HF]"


def _stale_warning() -> str | None:
    """Warn if the target book is older than the normal weekend gap — i.e. the Sunday
    refresh likely didn't run. A Friday-dated book on Monday (~3 days) is normal; a book
    older than stale_book_max_days means a refresh cycle was missed."""
    with get_conn() as c:
        row = c.execute("SELECT MAX(asof_date) d FROM target_portfolio").fetchone()
    asof = row["d"] if row else None
    if not asof:
        return "no target book found in the database"
    try:
        age = (date.today() - date.fromisoformat(asof)).days
    except (ValueError, TypeError):
        return None
    limit = int(cfg.get("execution.stale_book_max_days", 4))
    if age > limit:
        return (f"book is {age} calendar days old (asof {asof}) — the weekly refresh may "
                "not have run, so this data is STALE")
    return None


def main() -> None:
    when = date.today().isoformat()
    if not autoexec_state.is_enabled():
        log.info("auto-execution is OFF (dashboard toggle) — skipping; no orders placed")
        return
    stale = _stale_warning()  # flagged in the confirmation email below; we still trade
    if stale:
        log.warning("stale-data guard: %s", stale)
    try:
        summary = executor.run(dry_run=False)
    except Exception as e:  # noqa: BLE001
        log.exception("auto-execution crashed")
        send_email(f"{TAG} {when} — auto-execution ERROR",
                   f"The Monday auto-execution raised an exception and placed no orders:\n\n{e!r}")
        return

    if summary.get("halted"):
        send_email(f"{TAG} {when} — NOT traded: kill-switch active",
                   "The HALT lock is set, so NO orders were placed. Review, then clear it "
                   "with: run_risk.py --clear-halt")
        log.error("halted; emailed")
        return

    if summary.get("aggregate_reject"):
        send_email(f"{TAG} {when} — NOT traded: failed risk veto",
                   "The target book failed the aggregate pre-trade veto, so NO orders were "
                   f"placed.\n\n{json.dumps(summary['aggregate_reject'], indent=2)}")
        log.error("veto reject; emailed")
        return

    agg = summary.get("aggregate", {})
    warn = f"⚠ TRADED ON STALE DATA — {stale}\n\n" if stale else ""
    body = warn + (
        f"Monday auto-execution complete ({when}).\n\n"
        f"Orders placed:   {summary.get('executed')}\n"
        f"Target names:    {summary.get('target')}\n"
        f"Veto-rejected:   {summary.get('veto_rejected')}\n"
        f"Order states:    {summary.get('order_states')}\n\n"
        f"Book exposure:   gross {agg.get('gross')}, net {agg.get('net')}, "
        f"net beta {agg.get('net_beta')}\n\n"
        "Sizing is a % of live account equity, within the veto caps. Review fills on the "
        "dashboard (Execution / Performance). The 5-min risk monitor manages it intraday."
    )
    subject = f"{TAG} {when} — executed {summary.get('executed')} orders"
    if stale:
        subject += " ⚠ STALE"
    send_email(subject, body)
    log.info("executed + emailed: %s", summary)


if __name__ == "__main__":
    main()
