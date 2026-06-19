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

from core.log import get_logger
from core.notify import send_email
from execution import autoexec_state, executor

log = get_logger("auto_execute")
TAG = "[Mediajedi HF]"


def main() -> None:
    when = date.today().isoformat()
    if not autoexec_state.is_enabled():
        log.info("auto-execution is OFF (dashboard toggle) — skipping; no orders placed")
        return
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
    body = (
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
    send_email(f"{TAG} {when} — executed {summary.get('executed')} orders", body)
    log.info("executed + emailed: %s", summary)


if __name__ == "__main__":
    main()
