"""Alpaca broker connection. DEFAULTS TO PAPER (paper=True hardcodes the paper
endpoint). Live trading requires BOTH config mode: live AND a typed confirmation.
All API calls go through exponential-backoff retry."""
from __future__ import annotations

import time
from dataclasses import dataclass

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest

from core.config import cfg, env
from core.log import get_logger

log = get_logger("broker")

LIVE_CONFIRMATION = "YES I UNDERSTAND THE RISKS"


@dataclass
class Position:
    symbol: str
    qty: float
    market_value: float
    unrealized_pl: float
    avg_entry_price: float


class Broker:
    def __init__(self, confirm_fn=input):
        mode = str(cfg.get("fund.mode", "paper")).lower()
        self.paper = mode != "live"
        if not self.paper:
            # Live requires an explicit typed confirmation in addition to config.
            if confirm_fn(f'Type "{LIVE_CONFIRMATION}" to trade LIVE: ').strip() != LIVE_CONFIRMATION:
                raise SystemExit("Live trading not confirmed — aborting.")
            log.warning("LIVE TRADING ENABLED")
        self.client = TradingClient(env("ALPACA_API_KEY", required=True),
                                    env("ALPACA_SECRET_KEY", required=True), paper=self.paper)
        log.info("Broker connected (paper=%s)", self.paper)

    def _retry(self, fn, *args, attempts: int = 5, **kwargs):
        delay = 1.0
        for i in range(attempts):
            try:
                return fn(*args, **kwargs)
            except APIError as e:
                if 400 <= getattr(e, "status_code", 500) < 500 and getattr(e, "status_code", 0) != 429:
                    raise  # client errors (except rate limit) aren't retryable
                last = e
            except Exception as e:  # noqa: BLE001 - network/transient
                last = e
            log.warning("API retry %d/%d after %.1fs (%s)", i + 1, attempts, delay, last)
            time.sleep(delay)
            delay = min(delay * 2, 30)
        raise last

    # --- reads ---
    def account(self):
        return self._retry(self.client.get_account)

    def equity(self) -> float:
        return float(self.account().equity)

    def is_market_open(self) -> bool:
        return bool(self._retry(self.client.get_clock).is_open)

    def positions(self) -> dict[str, Position]:
        out = {}
        for p in self._retry(self.client.get_all_positions):
            out[p.symbol] = Position(p.symbol, float(p.qty), float(p.market_value),
                                     float(p.unrealized_pl), float(p.avg_entry_price))
        return out

    def get_asset(self, symbol: str):
        return self._retry(self.client.get_asset, symbol)

    def open_orders(self) -> list:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest
        return self._retry(self.client.get_orders,
                           filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))

    # --- orders ---
    def submit_limit(self, symbol: str, qty: float, side: str, limit_price: float):
        req = LimitOrderRequest(
            symbol=symbol, qty=qty,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY, limit_price=round(limit_price, 2))
        return self._retry(self.client.submit_order, order_data=req)

    def get_order(self, order_id):
        return self._retry(self.client.get_order_by_id, order_id)

    def cancel_order(self, order_id) -> None:
        try:
            self._retry(self.client.cancel_order_by_id, order_id)
        except APIError as e:
            log.warning("cancel failed for %s: %s", order_id, e)

    def close_position(self, symbol: str) -> None:
        try:
            self._retry(self.client.close_position, symbol)
            log.info("closed position %s", symbol)
        except APIError as e:
            log.warning("close_position %s failed: %s", symbol, e)

    def close_all(self) -> None:
        self._retry(self.client.close_all_positions, cancel_orders=True)
        log.warning("closed ALL positions and cancelled open orders")

    def last_equity(self) -> float:
        return float(self.account().last_equity)

    def sync_state(self) -> dict[str, Position]:
        acct = self.account()
        pos = self.positions()
        log.info("Synced: equity=%s cash=%s positions=%d", acct.equity, acct.cash, len(pos))
        return pos
