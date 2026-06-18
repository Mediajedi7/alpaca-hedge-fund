"""Quality — 8 sub-factors incl. Piotroski F-Score (0-9) and Altman Z-Score.
compute() returns (subscores, extras) where extras carries raw piotroski/altman_z."""
from __future__ import annotations

import numpy as np
import pandas as pd

from factors.base import ScoringContext, sector_percentile


def _latest(hist: pd.DataFrame, col: str):
    return hist[col].iloc[-1] if (hist is not None and col in hist and len(hist)) else np.nan


def _ago(hist: pd.DataFrame, col: str, q: int = 4):
    """Value q quarters ago."""
    if hist is None or col not in hist or len(hist) <= q:
        return np.nan
    return hist[col].iloc[-1 - q]


def _ttm(hist: pd.DataFrame, col: str) -> float:
    if hist is None or col not in hist or len(hist) < 4:
        return np.nan
    vals = hist[col].tail(4)
    return float(vals.sum()) if vals.notna().all() else np.nan


def _piotroski(hist: pd.DataFrame) -> float:
    """9 binary signals, latest quarter vs 4 quarters ago. NaN if too little history."""
    if hist is None or len(hist) < 5:
        return np.nan
    f = lambda c: _latest(hist, c)        # noqa: E731
    p = lambda c: _ago(hist, c, 4)        # noqa: E731
    roa, roa_prior = f("roa"), p("roa")
    cfo, ni, ta = f("operating_cash_flow"), f("net_income"), f("total_assets")
    score = 0
    score += 1 if (pd.notna(roa) and roa > 0) else 0
    score += 1 if (pd.notna(cfo) and cfo > 0) else 0
    score += 1 if (pd.notna(roa) and pd.notna(roa_prior) and roa > roa_prior) else 0
    score += 1 if (pd.notna(cfo) and pd.notna(ni) and cfo > ni) else 0
    score += 1 if (pd.notna(f("debt_to_equity")) and pd.notna(p("debt_to_equity"))
                   and f("debt_to_equity") < p("debt_to_equity")) else 0
    score += 1 if (pd.notna(f("current_ratio")) and pd.notna(p("current_ratio"))
                   and f("current_ratio") > p("current_ratio")) else 0
    score += 1 if (pd.notna(f("shares_outstanding")) and pd.notna(p("shares_outstanding"))
                   and f("shares_outstanding") <= p("shares_outstanding")) else 0
    score += 1 if (pd.notna(f("gross_margin")) and pd.notna(p("gross_margin"))
                   and f("gross_margin") > p("gross_margin")) else 0
    score += 1 if (pd.notna(f("asset_turnover")) and pd.notna(p("asset_turnover"))
                   and f("asset_turnover") > p("asset_turnover")) else 0
    return float(score)


def _altman_z(hist: pd.DataFrame, mktcap: float) -> float:
    ta = _latest(hist, "total_assets")
    if hist is None or pd.isna(ta) or not ta:
        return np.nan
    wc = _latest(hist, "working_capital")
    re = _latest(hist, "retained_earnings")
    ebit = _ttm(hist, "ebit")
    sales = _ttm(hist, "revenue")
    tl = _latest(hist, "total_liabilities")
    if any(pd.isna(x) for x in (wc, re, ebit, sales, tl)) or pd.isna(mktcap) or not tl:
        return np.nan
    return (1.2 * wc / ta + 1.4 * re / ta + 3.3 * ebit / ta
            + 0.6 * mktcap / tl + 1.0 * sales / ta)


def compute(ctx: ScoringContext) -> tuple[pd.DataFrame, pd.DataFrame]:
    roe_stab, gm_lvl, gm_trend, de, cfo_ni, accruals, piotr, altman = ({} for _ in range(8))
    for t in ctx.tickers:
        hist = ctx.fund_hist_q.get(t)
        f = ctx.fund_latest_q.get(t)
        if hist is None or f is None:
            continue
        roes = hist["roe"].tail(12).dropna()
        roe_stab[t] = float(roes.std()) if len(roes) >= 4 else np.nan
        gm_lvl[t] = _latest(hist, "gross_margin")
        gm_now, gm_ago = _latest(hist, "gross_margin"), _ago(hist, "gross_margin", 4)
        gm_trend[t] = (gm_now - gm_ago) if (pd.notna(gm_now) and pd.notna(gm_ago)) else np.nan
        de[t] = _latest(hist, "debt_to_equity")
        cfo_ni[t] = _latest(hist, "cfo_to_ni")
        accruals[t] = _latest(hist, "accruals_ratio")
        piotr[t] = _piotroski(hist)
        mktcap = float(f["market_cap"]) if pd.notna(f.get("market_cap")) else np.nan
        altman[t] = _altman_z(hist, mktcap)

    sm = ctx.sector_map
    subscores = pd.DataFrame({
        "roe_stability": sector_percentile(pd.Series(roe_stab), sm, False),   # lower std = better
        "gross_margin_level": sector_percentile(pd.Series(gm_lvl), sm, True),
        "gross_margin_trend": sector_percentile(pd.Series(gm_trend), sm, True),
        "debt_to_equity_inv": sector_percentile(pd.Series(de), sm, False),    # lower leverage = better
        "cfo_to_ni": sector_percentile(pd.Series(cfo_ni), sm, True),
        "accruals_inv": sector_percentile(pd.Series(accruals), sm, False),    # low accruals = better
        "piotroski": sector_percentile(pd.Series(piotr), sm, True),
        "altman_z": sector_percentile(pd.Series(altman), sm, True),
    })
    extras = pd.DataFrame({"piotroski": pd.Series(piotr), "altman_z": pd.Series(altman)})
    return subscores, extras
