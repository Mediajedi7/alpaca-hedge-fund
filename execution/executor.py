"""Order executor: turns the Layer 4 target_portfolio into Alpaca paper orders.
Per trade: pre-trade veto -> short-availability -> limit at close*(1±0.001) ->
chunk if > 2% ADV -> submit, poll every 5s up to 120s, cancel+retry (3x). Records
signal_price for slippage and logs every order."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

from alpaca.trading.enums import OrderStatus

from core.config import cfg
from core.db import get_conn
from core.log import get_logger
from data.universe import get_sector_map
from execution import costs, short_check
from execution.broker import Broker
from execution.order_manager import OrderManager
from portfolio import inputs
from risk.pre_trade import halt_active, screen_target

log = get_logger("executor")


@dataclass
class Trade:
    ticker: str
    side: str            # buy | sell
    shares: float
    signal_price: float
    limit_price: float
    is_closing: bool
    target_weight: float


def _last_close(tickers: list[str]) -> dict[str, float]:
    out = {}
    with get_conn() as conn:
        for t in tickers:
            row = conn.execute(
                "SELECT close FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)
            ).fetchone()
            if row:
                out[t] = float(row["close"])
    return out


def _load_target() -> dict[str, float]:
    with get_conn() as conn:
        asof = conn.execute("SELECT MAX(asof_date) d FROM target_portfolio").fetchone()["d"]
        rows = conn.execute(
            "SELECT ticker, weight FROM target_portfolio WHERE asof_date=?", (asof,)).fetchall()
    return {r["ticker"]: r["weight"] for r in rows}


def plan_trades(target: dict[str, float], broker: Broker, aum: float) -> list[Trade]:
    """Diff target weights against current positions into buy/sell trades.

    Prices off the LIVE quote (last close only as a fallback) and sets a marketable limit
    THROUGH the quote, so liquid names fill promptly instead of resting on a stale price.
    """
    current = broker.positions()
    offset = float(cfg.get("execution.marketable_offset", 0.003))
    syms = set(target) | set(current)
    closes = _last_close(list(syms))
    live = broker.latest_prices(list(syms))  # live quotes; per-name fallback to last close
    cur_shares = {s: p.qty for s, p in current.items()}

    trades = []
    for s in sorted(syms):
        px = live.get(s) or closes.get(s)
        if not px:
            continue
        tgt_shares = round(target.get(s, 0.0) * aum / px)
        cur_q = cur_shares.get(s, 0.0)
        delta = tgt_shares - cur_q
        if abs(delta) < 1:
            continue
        side = "buy" if delta > 0 else "sell"
        is_closing = (abs(tgt_shares) < abs(cur_q) and tgt_shares * cur_q >= 0) or tgt_shares == 0
        # marketable: cross the live quote so the order fills, capped at `offset`
        limit = px * (1 + offset) if side == "buy" else px * (1 - offset)
        trades.append(Trade(s, side, abs(delta), px, limit, is_closing, target.get(s, 0.0)))
    return trades


def _poll_fill(broker: Broker, om: OrderManager, order_id, ticker: str) -> tuple[float, float | None]:
    """Poll up to time_in_force_secs. Return (filled_qty, filled_avg_price)."""
    tif = int(cfg.get("execution.time_in_force_secs", 120))
    poll = int(cfg.get("execution.poll_interval_secs", 5))
    waited = 0
    while waited < tif:
        time.sleep(poll)
        waited += poll
        o = broker.get_order(order_id)
        if o.status == OrderStatus.FILLED:
            om.set_status(str(order_id), "filled")
            return float(o.filled_qty), float(o.filled_avg_price)
        if o.status == OrderStatus.PARTIALLY_FILLED:
            om.set_status(str(order_id), "partial")
        if o.status in (OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED):
            break
    o = broker.get_order(order_id)
    return float(o.filled_qty or 0), (float(o.filled_avg_price) if o.filled_avg_price else None)


def _execute_trade(broker: Broker, om: OrderManager, trade: Trade) -> None:
    adv = inputs.adv_dollar([trade.ticker]).get(trade.ticker)
    chunk_pct = float(cfg.get("execution.chunk_threshold_pct_adv", 0.02))
    max_retries = int(cfg.get("execution.max_retries", 3))

    # chunk if order notional exceeds 2% ADV
    chunk_shares = trade.shares
    if adv and trade.shares * trade.signal_price > chunk_pct * adv:
        max_chunk = max(1, math.floor(chunk_pct * adv / trade.signal_price))
        chunk_shares = max_chunk
    remaining = trade.shares

    while remaining >= 1:
        this = min(remaining, chunk_shares)
        filled_total = 0.0
        for _ in range(max_retries):
            order = broker.submit_limit(trade.ticker, this, trade.side, trade.limit_price)
            om.register(str(order.id), trade.ticker, trade.side, this)
            fq, fp = _poll_fill(broker, om, order.id, trade.ticker)
            if fq < this:
                broker.cancel_order(order.id)
                om.set_status(str(order.id), "cancelled")
            if fq > 0:
                costs.log_order(trade.ticker, trade.side, fq, trade.limit_price, fp,
                                trade.signal_price, "filled", str(order.id))
                filled_total += fq
            if filled_total >= this - 1e-9:
                break
        if filled_total < this:
            costs.log_order(trade.ticker, trade.side, this - filled_total, trade.limit_price,
                            None, trade.signal_price, "unfilled")
            break  # give up remaining after retries
        remaining -= this


def run(dry_run: bool = True, max_orders: int | None = None) -> dict:
    broker = Broker()
    broker.sync_state()
    if halt_active() and not dry_run:
        log.error("HALT lock active — refusing to execute")
        return {"halted": True}

    aum = broker.equity()
    target = _load_target()
    sector_map = get_sector_map()
    betas = inputs.betas(list(target))

    # Pre-trade veto applied holistically to the whole target (Layer 5).
    screen = screen_target(target, betas, sector_map, aum=aum)
    approved_target = screen["approved"]
    agg = screen["aggregate"]
    if not all(agg[k] for k in ("gross_ok", "net_ok", "net_beta_ok", "sector_ok")) and not dry_run:
        log.error("Target fails aggregate veto %s — refusing to execute", agg)
        return {"aggregate_reject": agg}

    trades = plan_trades(approved_target, broker, aum)
    om = OrderManager(broker, install_sigint=not dry_run)
    executed, skipped, n = [], list(screen["rejections"].items()), 0
    for tr in trades:
        if max_orders and n >= max_orders:
            break
        # live per-order checks: halt + short availability
        if halt_active():
            log.error("HALT lock active mid-run — stopping")
            break
        if tr.side == "sell" and tr.target_weight < 0 and not tr.is_closing \
                and not short_check.is_shortable(broker, tr.ticker):
            skipped.append((tr.ticker, ["not shortable"]))
            continue
        n += 1
        if dry_run:
            log.info("DRY-RUN would %s %.0f %s @ limit %.2f (signal %.2f)%s",
                     tr.side, tr.shares, tr.ticker, tr.limit_price, tr.signal_price,
                     " [closing]" if tr.is_closing else "")
        else:
            # Resilient: a single bad symbol/order must not abort the rest of the book
            # (that once left a partial, unbalanced book). Log, record, and continue.
            try:
                _execute_trade(broker, om, tr)
            except Exception as e:  # noqa: BLE001
                log.error("order failed for %s (%s) — skipping", tr.ticker, e)
                skipped.append((tr.ticker, [f"order error: {e}"]))
                continue
        executed.append(tr.ticker)

    summary = {"target": len(target), "veto_rejected": len(screen["rejections"]),
               "trades_planned": len(trades), "executed": len(executed),
               "skipped": len(skipped), "dry_run": dry_run, "aggregate": agg,
               "order_states": om.counts()}
    log.info("Execution summary: %s", summary)
    return summary
