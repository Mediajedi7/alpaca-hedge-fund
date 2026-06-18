"""Source 2b — Fundamentals. Quarterly + annual income / balance-sheet / cash-flow
statements from FMP (Premium), with 24 derived ratios computed from the raw line
items. Falls back to yfinance if FMP is unavailable.

Stores one row per (ticker, period_end, period_type) in `fundamentals`."""
from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
import requests

from core.config import cfg, env
from core.db import ensure_tables, get_conn, set_meta
from core.log import get_logger
from data.universe import get_universe_tickers

log = get_logger("fundamentals")

FMP_BASE = "https://financialmodelingprep.com/stable"

# 24 derived ratios + the raw line items needed to compute them downstream (Altman, Piotroski).
_SCHEMA = """
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker          TEXT,
    period_end      TEXT,
    period_type     TEXT,          -- 'Q' or 'A'
    -- derived ratios (the 24)
    roe REAL, roa REAL, gross_margin REAL, operating_margin REAL, net_margin REAL,
    rev_growth_yoy REAL, rev_growth_qoq REAL, earnings_growth_yoy REAL, earnings_growth_qoq REAL,
    debt_to_equity REAL, fcf_yield REAL, current_ratio REAL, ar_to_revenue REAL,
    cfo_to_ni REAL, accruals_ratio REAL, retained_earnings REAL, working_capital REAL,
    total_liabilities REAL, ebit REAL, rd_expense REAL, shares_outstanding REAL,
    dividends_paid REAL, buybacks REAL, asset_turnover REAL,
    -- raw line items kept for Altman/Piotroski in Layer 2
    revenue REAL, net_income REAL, total_assets REAL, total_equity REAL,
    total_current_assets REAL, total_current_liabilities REAL, operating_cash_flow REAL,
    free_cash_flow REAL, gross_profit REAL, market_cap REAL,
    source          TEXT,
    updated_at      TEXT,
    PRIMARY KEY (ticker, period_end, period_type)
);
"""


def _safe_div(a, b):
    try:
        a = float(a); b = float(b)
        return a / b if b else None
    except (TypeError, ValueError):
        return None


def _fmp_get(endpoint: str, symbol: str, **params) -> list[dict]:
    """Call the FMP `stable` API (symbol passed as a query param, not in the path)."""
    key = env("FMP_API_KEY", required=True)
    params.update(symbol=symbol, apikey=key)
    r = requests.get(f"{FMP_BASE}/{endpoint}", params=params, timeout=30)
    if r.status_code != 200:
        log.warning("FMP %s(%s) -> HTTP %s", endpoint, symbol, r.status_code)
        return []
    data = r.json()
    return data if isinstance(data, list) else []


def _fetch_fmp(ticker: str, period: str, limit: int) -> pd.DataFrame:
    inc = _fmp_get("income-statement", ticker, period=period, limit=limit)
    bal = _fmp_get("balance-sheet-statement", ticker, period=period, limit=limit)
    cf = _fmp_get("cash-flow-statement", ticker, period=period, limit=limit)
    km = _fmp_get("key-metrics", ticker, period=period, limit=limit)
    if not inc or not bal or not cf:
        return pd.DataFrame()

    def idx(rows):
        return {r.get("date"): r for r in rows}

    bi, ci, ki = idx(bal), idx(cf), idx(km)
    rows = []
    for r in inc:
        d = r.get("date")
        b, c, k = bi.get(d, {}), ci.get(d, {}), ki.get(d, {})
        rows.append({
            "period_end": d,
            "revenue": r.get("revenue"),
            "gross_profit": r.get("grossProfit"),
            "operating_income": r.get("operatingIncome"),
            "net_income": r.get("netIncome"),
            "rd_expense": r.get("researchAndDevelopmentExpenses"),
            "shares_outstanding": r.get("weightedAverageShsOut"),
            "total_assets": b.get("totalAssets"),
            "total_current_assets": b.get("totalCurrentAssets"),
            "total_current_liabilities": b.get("totalCurrentLiabilities"),
            "total_liabilities": b.get("totalLiabilities"),
            "total_equity": b.get("totalStockholdersEquity"),
            "total_debt": b.get("totalDebt"),
            "net_receivables": b.get("netReceivables"),
            "retained_earnings": b.get("retainedEarnings"),
            "operating_cash_flow": c.get("operatingCashFlow"),
            "free_cash_flow": c.get("freeCashFlow"),
            "dividends_paid": c.get("netDividendsPaid", c.get("commonDividendsPaid")),
            "buybacks": c.get("commonStockRepurchased"),
            "market_cap": k.get("marketCap"),
        })
    return pd.DataFrame(rows).sort_values("period_end").reset_index(drop=True)


def _compute_ratios(df: pd.DataFrame) -> pd.DataFrame:
    """Add the 24 derived ratios. df is sorted ascending by period_end."""
    if df.empty:
        return df
    out = df.copy()
    sd = _safe_div
    out["roe"] = out.apply(lambda r: sd(r.net_income, r.total_equity), axis=1)
    out["roa"] = out.apply(lambda r: sd(r.net_income, r.total_assets), axis=1)
    out["gross_margin"] = out.apply(lambda r: sd(r.gross_profit, r.revenue), axis=1)
    out["operating_margin"] = out.apply(lambda r: sd(r.operating_income, r.revenue), axis=1)
    out["net_margin"] = out.apply(lambda r: sd(r.net_income, r.revenue), axis=1)
    out["debt_to_equity"] = out.apply(lambda r: sd(r.total_debt, r.total_equity), axis=1)
    out["fcf_yield"] = out.apply(lambda r: sd(r.free_cash_flow, r.market_cap), axis=1)
    out["current_ratio"] = out.apply(lambda r: sd(r.total_current_assets, r.total_current_liabilities), axis=1)
    out["ar_to_revenue"] = out.apply(lambda r: sd(r.net_receivables, r.revenue), axis=1)
    out["cfo_to_ni"] = out.apply(lambda r: sd(r.operating_cash_flow, r.net_income), axis=1)
    out["accruals_ratio"] = out.apply(
        lambda r: sd((r.net_income or 0) - (r.operating_cash_flow or 0), r.total_assets), axis=1)
    out["working_capital"] = out["total_current_assets"].fillna(0) - out["total_current_liabilities"].fillna(0)
    out["asset_turnover"] = out.apply(lambda r: sd(r.revenue, r.total_assets), axis=1)
    out["ebit"] = out["operating_income"]
    out["total_liabilities"] = out["total_liabilities"]
    out["dividends_paid"] = out["dividends_paid"].abs()
    out["buybacks"] = out["buybacks"].abs()

    # Growth: QoQ = vs prior row; YoY = vs 4 rows back (quarterly) / 1 back (annual)
    yoy_lag = 4 if (out.get("period_type", pd.Series(["Q"])).iloc[0] == "Q") else 1
    out["rev_growth_qoq"] = out["revenue"].pct_change(1)
    out["rev_growth_yoy"] = out["revenue"].pct_change(yoy_lag)
    out["earnings_growth_qoq"] = out["net_income"].pct_change(1)
    out["earnings_growth_yoy"] = out["net_income"].pct_change(yoy_lag)
    return out


_RATIO_COLS = [
    "roe", "roa", "gross_margin", "operating_margin", "net_margin", "rev_growth_yoy",
    "rev_growth_qoq", "earnings_growth_yoy", "earnings_growth_qoq", "debt_to_equity",
    "fcf_yield", "current_ratio", "ar_to_revenue", "cfo_to_ni", "accruals_ratio",
    "retained_earnings", "working_capital", "total_liabilities", "ebit", "rd_expense",
    "shares_outstanding", "dividends_paid", "buybacks", "asset_turnover",
]
_RAW_COLS = [
    "revenue", "net_income", "total_assets", "total_equity", "total_current_assets",
    "total_current_liabilities", "operating_cash_flow", "free_cash_flow", "gross_profit",
    "market_cap",
]


def _store(ticker: str, df: pd.DataFrame, period_type: str, source: str) -> int:
    if df.empty:
        return 0
    now = datetime.utcnow().isoformat()
    cols = ["ticker", "period_end", "period_type"] + _RATIO_COLS + _RAW_COLS + ["source", "updated_at"]
    placeholders = ",".join("?" * len(cols))
    records = []
    for r in df.itertuples():
        vals = {c: getattr(r, c, None) for c in _RATIO_COLS + _RAW_COLS}
        rec = [ticker, r.period_end, period_type] + [vals[c] for c in _RATIO_COLS] \
              + [vals[c] for c in _RAW_COLS] + [source, now]
        records.append([None if pd.isna(v) else v for v in rec])
    with get_conn() as conn:
        conn.executemany(
            f"INSERT OR REPLACE INTO fundamentals ({','.join(cols)}) VALUES ({placeholders})",
            records,
        )
    return len(records)


def update_fundamentals(tickers: list[str] | None = None, sleep: float = 0.0) -> int:
    ensure_tables(_SCHEMA)
    tickers = tickers or get_universe_tickers()
    primary = cfg.get("data.fundamentals_provider", "fmp")
    total = 0
    for i, t in enumerate(tickers, 1):
        stored = 0
        if primary == "fmp":
            try:
                q = _compute_ratios(_fetch_fmp(t, "quarter", 16))
                q["period_type"] = "Q" if not q.empty else "Q"
                a = _compute_ratios(_fetch_fmp(t, "annual", 6))
                a["period_type"] = "A" if not a.empty else "A"
                stored += _store(t, q, "Q", "fmp")
                stored += _store(t, a, "A", "fmp")
            except Exception as e:  # noqa: BLE001
                log.warning("FMP fundamentals failed for %s: %s", t, e)
        if stored == 0:
            stored += _yfinance_fallback(t)
        total += stored
        if i % 25 == 0:
            log.info("fundamentals: %d/%d tickers (%d rows)", i, len(tickers), total)
        if sleep:
            time.sleep(sleep)
    set_meta("fundamentals_updated_at", datetime.utcnow().isoformat())
    log.info("Fundamentals updated: %d rows across %d tickers", total, len(tickers))
    return total


def _yfinance_fallback(ticker: str) -> int:
    """Best-effort: fewer quarters, computes what it can from yfinance statements."""
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        inc = tk.quarterly_financials.T
        bal = tk.quarterly_balance_sheet.T
        cf = tk.quarterly_cashflow.T
        if inc.empty:
            return 0
        rows = []
        for dt in inc.index:
            def g(frame, *names):
                for n in names:
                    if n in frame.columns and dt in frame.index:
                        v = frame.loc[dt, n]
                        if pd.notna(v):
                            return float(v)
                return None
            rows.append({
                "period_end": pd.Timestamp(dt).strftime("%Y-%m-%d"),
                "revenue": g(inc, "Total Revenue"),
                "gross_profit": g(inc, "Gross Profit"),
                "operating_income": g(inc, "Operating Income"),
                "net_income": g(inc, "Net Income"),
                "rd_expense": g(inc, "Research And Development"),
                "shares_outstanding": g(inc, "Diluted Average Shares"),
                "total_assets": g(bal, "Total Assets"),
                "total_current_assets": g(bal, "Current Assets"),
                "total_current_liabilities": g(bal, "Current Liabilities"),
                "total_liabilities": g(bal, "Total Liabilities Net Minority Interest"),
                "total_equity": g(bal, "Stockholders Equity"),
                "total_debt": g(bal, "Total Debt"),
                "net_receivables": g(bal, "Receivables", "Accounts Receivable"),
                "retained_earnings": g(bal, "Retained Earnings"),
                "operating_cash_flow": g(cf, "Operating Cash Flow"),
                "free_cash_flow": g(cf, "Free Cash Flow"),
                "dividends_paid": g(cf, "Cash Dividends Paid"),
                "buybacks": g(cf, "Repurchase Of Capital Stock"),
                "market_cap": None,
            })
        df = _compute_ratios(pd.DataFrame(rows).sort_values("period_end").reset_index(drop=True))
        return _store(ticker, df, "Q", "yfinance")
    except Exception as e:  # noqa: BLE001
        log.warning("yfinance fundamentals fallback failed for %s: %s", ticker, e)
        return 0


if __name__ == "__main__":
    import sys
    test = sys.argv[1:] or ["AAPL", "MSFT"]
    n = update_fundamentals(test)
    print(f"Stored {n} fundamental rows for {test}")
