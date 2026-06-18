"""Barra-style factor risk model. Daily cross-sectional regressions of stock returns
on standardized factor exposures (the 8 parent scores, z-scored) produce factor
returns, the factor covariance matrix, and per-stock specific variance. Builds the
predicted covariance Σ = XFXᵀ + diag(specific) and implements CovarianceProvider so
it can replace the historical cov in the Layer 4 MVO. Also decomposes portfolio risk
into factor/specific variance and per-name MCTR."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.config import cfg
from core.db import get_conn
from core.log import get_logger
from factors.base import PARENTS
from portfolio import inputs

log = get_logger("factor_risk_model")

TRADING_DAYS = 252


def _zscore(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean()
    sd = df.std(ddof=0).replace(0, 1.0)
    return (df - mu) / sd


@dataclass
class FactorRiskModel:
    lookback: int = field(default_factory=lambda: int(cfg.get("risk.factor_model.lookback_days", 120)))
    tickers: list[str] = field(default_factory=list)
    X: np.ndarray | None = None             # N x K standardized exposures
    factor_cov: np.ndarray | None = None    # K x K annualized
    specific_var: np.ndarray | None = None  # N annualized
    _idx: dict = field(default_factory=dict)

    def fit(self) -> "FactorRiskModel":
        with get_conn() as conn:
            asof = conn.execute("SELECT MAX(asof_date) d FROM scores").fetchone()["d"]
            scores = pd.read_sql_query(
                f"SELECT ticker, {','.join(PARENTS)} FROM scores WHERE asof_date=?",
                conn, params=(asof,)).set_index("ticker")

        rets = inputs.returns(list(scores.index), self.lookback)
        common = [t for t in scores.index if t in rets.columns]
        # keep only stocks with a fully finite return history (lstsq needs clean rows)
        rets = rets[common].replace([np.inf, -np.inf], np.nan).dropna(axis=1, how="any")
        # ...and a fully populated exposure row (a single NaN poisons every regression)
        expo = scores.loc[list(rets.columns), PARENTS].astype(float).dropna(how="any")
        common = list(expo.index)
        rets = rets[common]
        X = _zscore(expo).to_numpy()                                # N x K
        Xa = np.column_stack([np.ones(len(common)), X])             # intercept (alpha)
        R = rets.to_numpy()                                          # T x N

        T, K = R.shape[0], X.shape[1]
        F_ts = np.zeros((T, K))
        E = np.zeros((T, len(common)))
        for t in range(T):
            coef, *_ = np.linalg.lstsq(Xa, R[t], rcond=None)        # [alpha, f_1..f_K]
            F_ts[t] = coef[1:]
            E[t] = R[t] - Xa @ coef

        self.tickers = common
        self.X = X
        self.factor_cov = np.cov(F_ts, rowvar=False) * TRADING_DAYS
        self.specific_var = E.var(axis=0, ddof=0) * TRADING_DAYS
        self._idx = {t: i for i, t in enumerate(common)}
        log.info("Factor model fit: %d stocks, %d factors, %d days", len(common), K, T)
        return self

    def _predicted_cov(self, idxs: list[int]) -> np.ndarray:
        Xs = self.X[idxs]
        spec = self.specific_var[idxs]
        return Xs @ self.factor_cov @ Xs.T + np.diag(spec)

    def cov(self, tickers: list[str]) -> tuple[np.ndarray, list[str]]:
        """CovarianceProvider interface — predicted cov for the covered subset."""
        if self.X is None:
            self.fit()
        ordered = [t for t in tickers if t in self._idx]
        if len(ordered) < 2:
            raise ValueError("factor model covers <2 of the requested tickers")
        return self._predicted_cov([self._idx[t] for t in ordered]), ordered

    def factor_contributions(self, weights: dict[str, float]) -> dict:
        """Each factor's share of total FACTOR variance + portfolio factor exposure."""
        if self.X is None:
            self.fit()
        names = [t for t in weights if t in self._idx]
        idxs = [self._idx[t] for t in names]
        w = np.array([weights[t] for t in names])
        exp = w @ self.X[idxs]                       # K factor exposures
        fexp = self.factor_cov @ exp
        fvar = float(exp @ fexp)
        out = {}
        for k, fac in enumerate(PARENTS):
            share = (exp[k] * fexp[k] / fvar) if fvar else 0.0
            out[fac] = {"exposure": float(exp[k]), "share": float(share)}
        return out

    def standardized_exposures(self, tickers: list[str]) -> tuple[np.ndarray, list[str]]:
        """Return (N x K z-scored exposures, covered tickers) for stress testing."""
        if self.X is None:
            self.fit()
        names = [t for t in tickers if t in self._idx]
        return self.X[[self._idx[t] for t in names]], names

    def decompose(self, weights: dict[str, float]) -> dict:
        """Factor/specific variance split + per-name MCTR; flags MCTR% > 1.5x weight%."""
        if self.X is None:
            self.fit()
        names = [t for t in weights if t in self._idx]
        idxs = [self._idx[t] for t in names]
        w = np.array([weights[t] for t in names])
        Xs = self.X[idxs]
        exp = w @ Xs                                   # K portfolio factor exposures
        factor_var = float(exp @ self.factor_cov @ exp)
        specific_var = float(np.sum(w**2 * self.specific_var[idxs]))
        total_var = factor_var + specific_var
        sigma = total_var ** 0.5

        Sigma = self._predicted_cov(idxs)
        cov_ip = Sigma @ w                             # cov(r_i, r_p)
        mctr = w * cov_ip / sigma if sigma > 0 else np.zeros_like(w)
        gross = float(np.abs(w).sum()) or 1.0
        mult = float(cfg.get("risk.factor_model.mctr_flag_multiple", 1.5))
        flags = []
        mctr_pct = {}
        for i, t in enumerate(names):
            mp = mctr[i] / sigma if sigma > 0 else 0.0     # MCTR fraction of total risk
            wp = abs(w[i]) / gross
            mctr_pct[t] = round(mp, 4)
            if abs(mp) > mult * wp:
                flags.append(t)
        return {
            "factor_var": factor_var, "specific_var": specific_var,
            "total_var": total_var, "annual_vol": round(sigma, 4),
            "factor_share": round(factor_var / total_var, 3) if total_var else None,
            "mctr_pct": mctr_pct, "disproportionate_risk_flags": flags,
        }
