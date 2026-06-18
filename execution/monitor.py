"""Intraday risk monitor — the loop that wires Layer 5 circuit breakers to broker
actions. Run as a single pass on a schedule (supercronic, every few minutes during
market hours) rather than an always-on watchdog: each call records NAV, evaluates
the breakers against live Alpaca equity, and acts.

Actions: SIZE_DOWN -> logged (applied at next rebalance); CLOSE_ALL_TODAY / KILL_SWITCH
-> cancel + flatten; FORCE_CLOSE -> close that one position. KILL_SWITCH also leaves the
HALT.lock that the pre-trade veto reads."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.db import ensure_tables, get_conn
from core.log import get_logger
from execution.broker import Broker
from risk import circuit_breakers as cb

log = get_logger("monitor")


def _week_open_nav(fallback: float) -> float:
    """Earliest recorded NAV within the last 7 days (week-open proxy)."""
    ensure_tables("CREATE TABLE IF NOT EXISTS equity_curve (ts TEXT PRIMARY KEY, nav REAL);")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT nav FROM equity_curve WHERE ts>=? ORDER BY ts ASC LIMIT 1", (cutoff,)).fetchone()
    return row["nav"] if row else fallback


def check_once(broker: Broker | None = None) -> list[dict]:
    broker = broker or Broker()
    acct = broker.account()
    nav = float(acct.equity)
    cb.record_nav(nav)

    positions = broker.positions()
    snap = cb.AccountSnapshot(
        nav=nav,
        day_open_nav=float(acct.last_equity),                 # prior trading-day close
        week_open_nav=_week_open_nav(float(acct.last_equity)),
        peak=cb.peak_nav(),
        position_pnl={s: p.unrealized_pl for s, p in positions.items()},
    )
    actions = cb.evaluate(snap)

    flatten = any(a["action"] in (cb.CLOSE_ALL_TODAY, cb.KILL_SWITCH) for a in actions)
    if flatten:
        broker.close_all()
    else:
        for a in actions:
            if a["action"] == cb.FORCE_CLOSE:
                broker.close_position(a["ticker"])
    if not actions:
        log.info("Monitor: NAV %.0f — no breakers triggered", nav)
    return actions


if __name__ == "__main__":
    import json
    print(json.dumps(check_once(), indent=2))
