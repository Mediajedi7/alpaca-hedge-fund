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
from core.notify import html_email, send_email
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
    def _alert(subject, plain, inner):
        send_email(subject, plain, html=html_email(
            "Monday auto-execution", inner, subtitle=when,
            banner="NO ORDERS PLACED", banner_class="alert-banner"))

    try:
        summary = executor.run(dry_run=False)
    except Exception as e:  # noqa: BLE001
        log.exception("auto-execution crashed")
        _alert(f"{TAG} {when} — auto-execution ERROR",
               f"Raised an exception and placed no orders:\n\n{e!r}",
               f"<p>The Monday auto-execution <b>raised an exception</b> and placed no "
               f"orders:</p><div class='note'><code>{e!r}</code></div>")
        return

    if summary.get("halted"):
        _alert(f"{TAG} {when} — NOT traded: kill-switch active",
               "The HALT lock is set, so NO orders were placed. Clear it with run_risk.py --clear-halt",
               "<p>The <b>kill-switch (HALT lock)</b> is set, so <b>no orders were placed.</b> "
               "Review, then clear it with <code>run_risk.py --clear-halt</code>.</p>")
        log.error("halted; emailed")
        return

    if summary.get("aggregate_reject"):
        _alert(f"{TAG} {when} — NOT traded: failed risk veto",
               f"Target failed the aggregate pre-trade veto; no orders placed.\n\n"
               f"{json.dumps(summary['aggregate_reject'], indent=2)}",
               "<p>The target book <b>failed the aggregate pre-trade veto</b>, so <b>no orders "
               f"were placed.</b></p><div class='note'><code>{json.dumps(summary['aggregate_reject'])}</code></div>")
        log.error("veto reject; emailed")
        return

    agg = summary.get("aggregate", {})
    warn_p = f"⚠ TRADED ON STALE DATA — {stale}\n\n" if stale else ""
    plain = warn_p + (
        f"Monday auto-execution complete ({when}).\n\n"
        f"Orders placed: {summary.get('executed')} | target {summary.get('target')} | "
        f"veto-rejected {summary.get('veto_rejected')}\n"
        f"Book: gross {agg.get('gross')}, net {agg.get('net')}, net beta {agg.get('net_beta')}\n"
    )
    warn_h = (f'<div class="alert-banner">⚠ TRADED ON STALE DATA — {stale}</div>' if stale else "")
    inner = warn_h + f"""
      <div class="stats-grid">
        <div class="stat-cell"><div class="stat-label">Orders placed</div><div class="stat-value">{summary.get('executed')}</div></div>
        <div class="stat-cell"><div class="stat-label">Target names</div><div class="stat-value">{summary.get('target')}</div></div>
        <div class="stat-cell"><div class="stat-label">Veto-rejected</div><div class="stat-value">{summary.get('veto_rejected')}</div></div>
      </div>
      <div class="stats-grid">
        <div class="stat-cell"><div class="stat-label">Gross</div><div class="stat-value">{agg.get('gross')}</div></div>
        <div class="stat-cell"><div class="stat-label">Net</div><div class="stat-value">{agg.get('net')}</div></div>
        <div class="stat-cell"><div class="stat-label">Net beta</div><div class="stat-value">{agg.get('net_beta')}</div></div>
      </div>
      <p>Sizing is a % of live account equity, within the veto caps. The 5-min risk monitor
      manages the book intraday.</p>"""
    subject = f"{TAG} {when} — executed {summary.get('executed')} orders" + (" ⚠ STALE" if stale else "")
    send_email(subject, plain, html=html_email("Monday auto-execution", inner, subtitle=when))
    log.info("executed + emailed: %s", summary)


if __name__ == "__main__":
    main()
