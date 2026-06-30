"""Alpaca broker connection. DEFAULTS TO PAPER (paper=True hardcodes the paper
endpoint). Live trading requires BOTH config mode: live AND a typed confirmation.
All API calls go through exponential-backoff retry."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest

from core.config import ROOT, cfg, env
from core.log import get_logger

log = get_logger("broker")

LIVE_CONFIRMATION = "YES I UNDERSTAND THE RISKS"


def _creds(paper: bool) -> tuple[str, str]:
    """Pick API creds for the mode. Live REQUIRES ALPACA_LIVE_*; paper prefers
    ALPACA_PAPER_* but falls back to the legacy ALPACA_API_KEY/SECRET_KEY so existing
    paper setups keep working unchanged. Keeping both name pairs in .env lets `fund.mode`
    flip paper<->live without swapping keys."""
    if paper:
        key = env("ALPACA_PAPER_API_KEY") or env("ALPACA_API_KEY", required=True)
        secret = env("ALPACA_PAPER_SECRET_KEY") or env("ALPACA_SECRET_KEY", required=True)
    else:
        key = env("ALPACA_LIVE_API_KEY", required=True)
        secret = env("ALPACA_LIVE_SECRET_KEY", required=True)
    return key, secret


def _live_armed(confirm_fn) -> bool:
    """Live trading needs an explicit confirmation. Non-interactive arming (so the cron
    auto-executor can trade live once a human has armed it via scripts.go_live): a lock
    file or env var holding the exact phrase. Otherwise fall back to an interactive prompt."""
    if (env("ALPACA_LIVE_CONFIRMED") or "").strip() == LIVE_CONFIRMATION:
        return True
    lock = Path(ROOT / cfg.get("execution.live_arm_lock", "cache/LIVE_ARMED.lock"))
    try:
        if lock.exists() and lock.read_text().strip() == LIVE_CONFIRMATION:
            log.warning("LIVE armed via lock file %s", lock)
            return True
    except OSError:
        pass
    return confirm_fn(f'Type "{LIVE_CONFIRMATION}" to trade LIVE: ').strip() == LIVE_CONFIRMATION


def _to_alpaca(symbol: str) -> str:
    """Our S&P universe writes class shares with '-' (BRK-B, BF-B); Alpaca uses '.'."""
    return symbol.replace("-", ".")


def _from_alpaca(symbol: str) -> str:
    return symbol.replace(".", "-")


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
            # Live requires explicit arming (config mode:live is necessary but NOT sufficient).
            if not _live_armed(confirm_fn):
                raise SystemExit("Live trading not confirmed — aborting.")
            log.warning("LIVE TRADING ENABLED")
        key, secret = _creds(self.paper)
        self.client = TradingClient(key, secret, paper=self.paper)
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
            sym = _from_alpaca(p.symbol)   # map back to our internal symbol
            out[sym] = Position(sym, float(p.qty), float(p.market_value),
                                float(p.unrealized_pl), float(p.avg_entry_price))
        return out

    def get_asset(self, symbol: str):
        return self._retry(self.client.get_asset, _to_alpaca(symbol))

    def _data_client(self):
        if getattr(self, "_data", None) is None:
            from alpaca.data.historical import StockHistoricalDataClient
            key, secret = _creds(self.paper)
            self._data = StockHistoricalDataClient(key, secret)
        return self._data

    def _feed(self):
        """Market-data feed for quote/trade requests. Default IEX (free). Set
        `execution.data_feed: sip` once a SIP subscription is active (required for live —
        see CLAUDE.md 'Going live'). Returns None to leave the SDK default (IEX)."""
        name = str(cfg.get("execution.data_feed", "") or "").lower()
        if name in ("sip", "iex"):
            from alpaca.data.enums import DataFeed
            return DataFeed.SIP if name == "sip" else DataFeed.IEX
        return None

    def latest_prices(self, symbols: list[str]) -> dict[str, float]:
        """Latest trade price per symbol from Alpaca market data (IEX feed on paper).
        Returns {our_symbol: price}; missing names are simply absent (caller falls back)."""
        if not symbols:
            return {}
        from alpaca.data.requests import StockLatestTradeRequest
        amap = {_to_alpaca(s): s for s in symbols}
        feed, out = self._feed(), {}
        kw = {"feed": feed} if feed else {}
        try:
            res = self._data_client().get_stock_latest_trade(
                StockLatestTradeRequest(symbol_or_symbols=list(amap), **kw))
            for asym, tr in res.items():
                out[amap.get(asym, _from_alpaca(asym))] = float(tr.price)
        except Exception as e:  # noqa: BLE001 - caller falls back to last close
            log.warning("latest_prices failed (%s) — falling back to last close", e)
        return out

    def latest_quotes(self, symbols: list[str]) -> dict[str, tuple[float, float]]:
        """Latest NBBO bid/ask per symbol from Alpaca market data (IEX feed on paper).
        Returns {our_symbol: (bid, ask)}; a name is OMITTED (caller falls back to the last
        trade) if it has no two-sided quote or an implausibly wide spread — off-hours IEX
        quotes can be 10%+ wide and would otherwise produce nonsensical limits."""
        if not symbols:
            return {}
        from alpaca.data.requests import StockLatestQuoteRequest
        max_spread = float(cfg.get("execution.max_quote_spread", 0.02))
        amap = {_to_alpaca(s): s for s in symbols}
        feed, out = self._feed(), {}
        kw = {"feed": feed} if feed else {}
        try:
            res = self._data_client().get_stock_latest_quote(
                StockLatestQuoteRequest(symbol_or_symbols=list(amap), **kw))
            for asym, q in res.items():
                bid, ask = float(q.bid_price), float(q.ask_price)
                if bid > 0 and ask >= bid and (ask - bid) / ((bid + ask) / 2.0) <= max_spread:
                    out[amap.get(asym, _from_alpaca(asym))] = (bid, ask)
        except Exception as e:  # noqa: BLE001 - caller falls back to last trade
            log.warning("latest_quotes failed (%s) — falling back to last trade", e)
        return out

    def open_orders(self) -> list:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest
        return self._retry(self.client.get_orders,
                           filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))

    # --- orders ---
    def submit_limit(self, symbol: str, qty: float, side: str, limit_price: float):
        req = LimitOrderRequest(
            symbol=_to_alpaca(symbol), qty=qty,
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
            self._retry(self.client.close_position, _to_alpaca(symbol))
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
