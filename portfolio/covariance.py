"""Covariance providers. Layer 4 uses HistoricalCovarianceProvider (120-day sample
cov, annualized). Layer 5's Barra factor model will implement the same `cov()`
interface (XFXᵀ + diag(specific)) and be swapped in without changing the optimizer."""
from __future__ import annotations

from typing import Protocol

import numpy as np

from core.config import cfg
from core.log import get_logger
from portfolio import inputs

log = get_logger("covariance")

TRADING_DAYS = 252


class CovarianceProvider(Protocol):
    def cov(self, tickers: list[str]) -> tuple[np.ndarray, list[str]]:
        """Return (annualized covariance matrix, ordered tickers it covers)."""
        ...


class HistoricalCovarianceProvider:
    def __init__(self, lookback: int | None = None):
        self.lookback = lookback or int(cfg.get("portfolio.mvo.cov_lookback_days", 120))

    def cov(self, tickers: list[str]) -> tuple[np.ndarray, list[str]]:
        rets = inputs.returns(tickers, self.lookback)
        rets = rets[[t for t in tickers if t in rets.columns]].dropna(axis=1, how="any")
        ordered = list(rets.columns)
        if len(ordered) < 2:
            raise ValueError("insufficient return history for covariance")
        cov = rets.cov().to_numpy() * TRADING_DAYS  # annualize
        log.info("Historical cov: %d names, %d-day lookback", len(ordered), self.lookback)
        return cov, ordered
