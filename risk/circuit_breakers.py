"""Circuit breakers — fire on ACTUAL dollar losses. Daily/weekly loss thresholds,
peak-to-now drawdown kill-switch (writes a halt lock the pre-trade veto reads), and
a per-position NAV-loss force-close. Pure logic + state; the intraday loop that calls
evaluate() with live Alpaca NAV is wired in Layer 6 (execution)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.config import ROOT, cfg
from core.db import ensure_tables, get_conn
from core.log import get_logger

log = get_logger("circuit_breakers")

SIZE_DOWN = "SIZE_DOWN"
CLOSE_ALL_TODAY = "CLOSE_ALL_TODAY"
KILL_SWITCH = "KILL_SWITCH"
FORCE_CLOSE = "FORCE_CLOSE"

_SCHEMA = "CREATE TABLE IF NOT EXISTS equity_curve (ts TEXT PRIMARY KEY, nav REAL);"


def _lock_path() -> Path:
    return Path(ROOT / cfg.get("risk.halt_lock_file", "cache/HALT.lock"))


def set_halt(reason: str) -> None:
    p = _lock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"{datetime.now(timezone.utc).isoformat()} {reason}\n")
    log.error("KILL SWITCH engaged: %s (lock: %s)", reason, p)


def clear_halt() -> bool:
    p = _lock_path()
    if p.exists():
        p.unlink()
        log.info("Halt lock cleared")
        return True
    return False


def record_nav(nav: float) -> None:
    ensure_tables(_SCHEMA)
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO equity_curve (ts, nav) VALUES (?,?)",
                     (datetime.now(timezone.utc).isoformat(), nav))


def peak_nav() -> float | None:
    ensure_tables(_SCHEMA)
    with get_conn() as conn:
        row = conn.execute("SELECT MAX(nav) m FROM equity_curve").fetchone()
    return row["m"] if row and row["m"] is not None else None


@dataclass
class AccountSnapshot:
    nav: float
    day_open_nav: float
    week_open_nav: float
    peak: float | None = None
    position_pnl: dict[str, float] = field(default_factory=dict)  # ticker -> unrealized $ P&L


def evaluate(snap: AccountSnapshot) -> list[dict]:
    """Return the list of breaker actions triggered by this snapshot."""
    cb = cfg.get("risk.circuit_breakers", {})
    actions: list[dict] = []

    daily = (snap.nav - snap.day_open_nav) / snap.day_open_nav if snap.day_open_nav else 0.0
    weekly = (snap.nav - snap.week_open_nav) / snap.week_open_nav if snap.week_open_nav else 0.0
    peak = snap.peak if snap.peak is not None else (peak_nav() or snap.nav)
    drawdown = (snap.nav - peak) / peak if peak else 0.0

    # Daily: close-all supersedes size-down
    if daily <= -cb["daily_loss_close_all"]["threshold"]:
        actions.append({"action": CLOSE_ALL_TODAY, "reason": f"daily loss {daily:.2%}"})
    elif daily <= -cb["daily_loss_size_down"]["threshold"]:
        actions.append({"action": SIZE_DOWN, "size_pct": cb["daily_loss_size_down"]["size_pct"],
                        "reason": f"daily loss {daily:.2%}"})

    if weekly <= -cb["weekly_loss_size_down"]["threshold"]:
        actions.append({"action": SIZE_DOWN, "size_pct": cb["weekly_loss_size_down"]["size_pct"],
                        "reason": f"weekly loss {weekly:.2%}"})

    if drawdown <= -cb["drawdown_kill_switch"]["threshold"]:
        set_halt(f"drawdown {drawdown:.2%}")
        actions.append({"action": KILL_SWITCH, "reason": f"drawdown {drawdown:.2%}"})

    pos_thr = cb["single_position_nav_loss"]["threshold"]
    for ticker, pnl in snap.position_pnl.items():
        if snap.nav and pnl / snap.nav <= -pos_thr:
            actions.append({"action": FORCE_CLOSE, "ticker": ticker,
                            "reason": f"{ticker} loss {pnl / snap.nav:.2%} of NAV"})

    if actions:
        log.warning("Circuit breakers fired: %s", [a["action"] for a in actions])
    return actions
