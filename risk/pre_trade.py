"""Pre-trade veto — ABSOLUTE, no override. 8 checks; ANY failure rejects the trade.
Closing/covering trades are always approved. The earnings 50% size-cut is applied
HERE (once). Every rejection is logged with timestamp + reason."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from core.config import ROOT, cfg
from core.db import ensure_tables, get_conn
from core.log import get_logger
from data.earnings_calendar import days_to_earnings
from portfolio import inputs

log = get_logger("pre_trade")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS veto_rejections (
    ts TEXT, ticker TEXT, reason TEXT
);
"""


@dataclass
class VetoResult:
    approved: bool
    adjusted_weight: float
    reasons: list[str] = field(default_factory=list)


def halt_active() -> bool:
    return Path(ROOT / cfg.get("risk.halt_lock_file", "cache/HALT.lock")).exists()


@dataclass
class PreTradeVeto:
    aum: float
    sector_map: dict[str, str]
    betas: dict[str, float]
    adv: dict[str, float]
    _returns: pd.DataFrame | None = None  # for pairwise correlation

    def _v(self, path, default):
        return float(cfg.get(path, default))

    def _corr_ok(self, ticker: str, existing: list[str]) -> bool:
        max_corr = self._v("risk.veto.max_pairwise_correlation", 0.80)
        peers = [t for t in existing if t != ticker]
        if not peers or self._returns is None or ticker not in self._returns.columns:
            return True
        for p in peers:
            if p in self._returns.columns:
                pair = self._returns[[ticker, p]].dropna()
                if len(pair) > 20 and abs(pair[ticker].corr(pair[p])) > max_corr:
                    return False
        return True

    def veto(self, current: dict[str, float], ticker: str, target_weight: float,
             is_closing: bool = False) -> VetoResult:
        """Validate setting `ticker` to `target_weight` given the `current` book."""
        ensure_tables(_SCHEMA)
        if is_closing:
            return VetoResult(True, target_weight, [])

        reasons: list[str] = []
        # 1. halt lock
        if halt_active():
            reasons.append("halt lock active")
        # 2. earnings blackout -> 50% size cut (applied here, once)
        w = target_weight
        dte = days_to_earnings(ticker)
        if dte is not None and dte <= self._v("risk.veto.earnings_blackout_days", 5):
            w *= self._v("risk.veto.earnings_size_cut", 0.50)
        # 3. liquidity <= 5% ADV
        a = self.adv.get(ticker)
        if a and abs(w) * self.aum > self._v("risk.veto.liquidity_max_pct_adv", 0.05) * a:
            reasons.append(f"liquidity > {self._v('risk.veto.liquidity_max_pct_adv', 0.05):.0%} ADV")
        # 4. position <= 5% AUM
        if abs(w) > self._v("risk.veto.position_max_pct_aum", 0.05) + 1e-9:
            reasons.append("position > 5% AUM")

        resulting = dict(current)
        resulting[ticker] = w
        # 5. sector single-side <= 25%
        sec = self.sector_map.get(ticker)
        side = np.sign(w)
        sec_exp = sum(v for t, v in resulting.items()
                      if self.sector_map.get(t) == sec and np.sign(v) == side)
        if abs(sec_exp) > self._v("risk.veto.sector_max_pct", 0.25) + 1e-9:
            reasons.append(f"sector {sec} > 25%")
        # 6. gross <= 165%, net in [-10%, +15%]
        gross = sum(abs(v) for v in resulting.values())
        net = sum(resulting.values())
        if gross > self._v("risk.veto.gross_max", 1.65) + 1e-9:
            reasons.append(f"gross {gross:.0%} > 165%")
        if not (self._v("risk.veto.net_min", -0.10) - 1e-9 <= net <= self._v("risk.veto.net_max", 0.15) + 1e-9):
            reasons.append(f"net {net:+.0%} out of [-10%, +15%]")
        # 7. |net beta| <= 0.20
        net_beta = sum(v * self.betas.get(t, 1.0) for t, v in resulting.items())
        if abs(net_beta) > self._v("risk.veto.net_beta_max", 0.20) + 1e-9:
            reasons.append(f"|net beta| {net_beta:.2f} > 0.20")
        # 8. pairwise correlation <= 0.80 with existing positions
        if not self._corr_ok(ticker, list(current.keys())):
            reasons.append("pairwise correlation > 0.80")

        if reasons:
            self._log(ticker, reasons)
            return VetoResult(False, w, reasons)
        return VetoResult(True, w, [])

    def _log(self, ticker: str, reasons: list[str]) -> None:
        ts = datetime.utcnow().isoformat()
        with get_conn() as conn:
            conn.executemany("INSERT INTO veto_rejections (ts,ticker,reason) VALUES (?,?,?)",
                             [(ts, ticker, r) for r in reasons])
        log.warning("VETO %s: %s", ticker, "; ".join(reasons))


def screen_target(weights: dict[str, float], betas: dict[str, float],
                  sector_map: dict[str, str], aum: float | None = None) -> dict:
    """Holistically validate a fully-built target portfolio. Per-position checks
    (earnings cut, liquidity, size, correlation) reject individual names; the
    aggregate checks (halt, gross, net, sector, net beta) are reported once for the
    whole book. (The per-trade `PreTradeVeto.veto` is for Layer 6's incremental orders.)"""
    aum = aum or float(cfg.get("portfolio.aum", 1_000_000))
    names = list(weights.keys())
    adv = inputs.adv_dollar(names)
    rets = inputs.returns(names, 120)
    veto = PreTradeVeto(aum=aum, sector_map=sector_map, betas=betas, adv=adv, _returns=rets)
    g = veto._v
    blackout, cut = g("risk.veto.earnings_blackout_days", 5), g("risk.veto.earnings_size_cut", 0.50)

    adjusted, rejections = {}, {}
    for t, w in weights.items():
        dte = days_to_earnings(t)
        adjusted[t] = w * cut if (dte is not None and dte <= blackout) else w

    approved = dict(adjusted)
    for t in names:
        rs = []
        a = adv.get(t)
        if a and abs(adjusted[t]) * aum > g("risk.veto.liquidity_max_pct_adv", 0.05) * a:
            rs.append("liquidity > 5% ADV")
        if abs(adjusted[t]) > g("risk.veto.position_max_pct_aum", 0.05) + 1e-9:
            rs.append("position > 5% AUM")
        if not veto._corr_ok(t, [x for x in names if x != t]):
            rs.append("pairwise correlation > 0.80")
        if rs:
            rejections[t] = rs
            veto._log(t, rs)
            approved.pop(t, None)

    gross = sum(abs(v) for v in approved.values())
    net = sum(approved.values())
    net_beta = sum(v * betas.get(t, 1.0) for t, v in approved.items())
    sec: dict[str, float] = {}
    for t, w in approved.items():
        key = (sector_map.get(t), w > 0)
        sec[key] = sec.get(key, 0.0) + abs(w)
    aggregate = {
        "halt_active": halt_active(),
        "gross": round(gross, 4), "gross_ok": gross <= g("risk.veto.gross_max", 1.65) + 1e-9,
        "net": round(net, 4),
        "net_ok": g("risk.veto.net_min", -0.10) - 1e-9 <= net <= g("risk.veto.net_max", 0.15) + 1e-9,
        "net_beta": round(net_beta, 4),
        "net_beta_ok": abs(net_beta) <= g("risk.veto.net_beta_max", 0.20) + 1e-9,
        "max_sector_single_side": round(max(sec.values(), default=0), 4),
        "sector_ok": max(sec.values(), default=0) <= g("risk.veto.sector_max_pct", 0.25) + 1e-9,
    }
    return {"approved": approved, "rejections": rejections, "aggregate": aggregate}
