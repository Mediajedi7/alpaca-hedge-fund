"""Tracks order lifecycle (pending/partial/filled/cancelled). On SIGINT, cancels
PENDING orders but keeps existing positions, then exits cleanly."""
from __future__ import annotations

import signal
import sys
import threading

from core.log import get_logger

log = get_logger("order_manager")

PENDING, PARTIAL, FILLED, CANCELLED = "pending", "partial", "filled", "cancelled"


class OrderManager:
    def __init__(self, broker, install_sigint: bool = True):
        self.broker = broker
        self.orders: dict[str, dict] = {}  # broker_order_id -> {ticker, status, ...}
        # signal handlers only work on the main thread — skip when run from a worker
        # thread (e.g. the Streamlit dashboard's manual override), where SIGINT isn't ours.
        if install_sigint and threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self._on_sigint)

    def register(self, order_id: str, ticker: str, side: str, shares: float) -> None:
        self.orders[order_id] = {"ticker": ticker, "side": side, "shares": shares, "status": PENDING}

    def set_status(self, order_id: str, status: str) -> None:
        if order_id in self.orders:
            self.orders[order_id]["status"] = status

    def pending_ids(self) -> list[str]:
        return [oid for oid, o in self.orders.items() if o["status"] in (PENDING, PARTIAL)]

    def counts(self) -> dict[str, int]:
        c = {PENDING: 0, PARTIAL: 0, FILLED: 0, CANCELLED: 0}
        for o in self.orders.values():
            c[o["status"]] = c.get(o["status"], 0) + 1
        return c

    def cancel_pending(self) -> None:
        for oid in self.pending_ids():
            log.info("cancelling pending order %s (%s)", oid, self.orders[oid]["ticker"])
            self.broker.cancel_order(oid)
            self.set_status(oid, CANCELLED)

    def _on_sigint(self, signum, frame) -> None:
        log.warning("SIGINT — cancelling pending orders, keeping positions")
        try:
            self.cancel_pending()
        finally:
            log.info("Order states at exit: %s", self.counts())
            sys.exit(130)
