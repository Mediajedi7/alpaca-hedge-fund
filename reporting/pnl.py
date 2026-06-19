"""External cash-flow ledger so dashboard P&L isn't fooled by deposits/withdrawals.

Total P&L = equity - cost_basis, where
    cost_basis = starting_capital + net external contributions (deposits +, withdrawals -)

A withdrawal lowers both equity and cost_basis by the same amount, so realized P&L is
unaffected — the dashboard keeps showing what the strategy actually earned, not how much
cash you've since pulled out (or added). Same idea for the intraday figure: subtract any
cash moved today so a transfer doesn't masquerade as a gain/loss.
"""
from __future__ import annotations

from datetime import date, datetime

from core.config import cfg
from core.db import ensure_tables, get_conn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cash_flows (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL,        -- ISO timestamp (UTC)
    amount REAL NOT NULL,        -- + deposit / funding, - withdrawal
    note   TEXT
);
"""


def record(amount: float, note: str = "") -> None:
    """Log an external cash flow: positive = deposit/funding, negative = withdrawal."""
    ensure_tables(_SCHEMA)
    with get_conn() as c:
        c.execute("INSERT INTO cash_flows (ts, amount, note) VALUES (?,?,?)",
                  (datetime.utcnow().isoformat(timespec="seconds"), float(amount), note))


def net_flows() -> float:
    ensure_tables(_SCHEMA)
    with get_conn() as c:
        return float(c.execute("SELECT COALESCE(SUM(amount),0) s FROM cash_flows").fetchone()["s"])


def net_flows_on(day: date) -> float:
    ensure_tables(_SCHEMA)
    with get_conn() as c:
        return float(c.execute(
            "SELECT COALESCE(SUM(amount),0) s FROM cash_flows WHERE substr(ts,1,10)=?",
            (day.isoformat(),)).fetchone()["s"])


def cost_basis() -> float:
    """Capital actually put in: the seed plus net deposits/withdrawals since."""
    return float(cfg.get("fund.starting_capital", 100_000)) + net_flows()


def total_pnl(equity: float) -> float:
    return equity - cost_basis()


def today_pnl(equity: float, last_equity: float) -> float:
    return equity - last_equity - net_flows_on(date.today())


def history(limit: int = 50) -> list[dict]:
    ensure_tables(_SCHEMA)
    with get_conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT ts, amount, note FROM cash_flows ORDER BY ts DESC LIMIT ?", (limit,))]
