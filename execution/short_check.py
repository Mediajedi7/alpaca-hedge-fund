"""Short-availability check via Alpaca asset flags (shortable / easy_to_borrow),
cached 7 days. Log and skip names that aren't shortable."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.config import cfg
from core.db import ensure_tables, get_conn
from core.log import get_logger

log = get_logger("short_check")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS short_availability (
    ticker TEXT PRIMARY KEY, shortable INTEGER, easy_to_borrow INTEGER, checked_at TEXT
);
"""


def _cached(ticker: str) -> dict | None:
    ensure_tables(_SCHEMA)
    days = int(cfg.get("execution.short_check_cache_days", 7))
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM short_availability WHERE ticker=?", (ticker,)).fetchone()
    if not row:
        return None
    if datetime.now(timezone.utc) - datetime.fromisoformat(row["checked_at"]) > timedelta(days=days):
        return None
    return {"shortable": bool(row["shortable"]), "easy_to_borrow": bool(row["easy_to_borrow"])}


def is_shortable(broker, ticker: str) -> bool:
    hit = _cached(ticker)
    if hit is None:
        try:
            a = broker.get_asset(ticker)
            hit = {"shortable": bool(a.shortable), "easy_to_borrow": bool(a.easy_to_borrow)}
        except Exception as e:  # noqa: BLE001
            log.warning("asset lookup failed for %s: %s", ticker, e)
            return False
        with get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO short_availability (ticker,shortable,easy_to_borrow,checked_at) "
                "VALUES (?,?,?,?)",
                (ticker, int(hit["shortable"]), int(hit["easy_to_borrow"]),
                 datetime.now(timezone.utc).isoformat()))
    if not hit["shortable"]:
        log.warning("%s not shortable — skipping", ticker)
    return hit["shortable"]
