"""Shared portfolio-construction helpers: the final per-ticker score (combined if
available, else quant composite), expected-return mapping, long/short candidate
selection, and target-portfolio storage."""
from __future__ import annotations

import pandas as pd

from core.config import cfg
from core.db import ensure_tables, get_conn
from core.log import get_logger

log = get_logger("construct")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS target_portfolio (
    asof_date       TEXT, ticker TEXT, side TEXT, weight REAL,
    method          TEXT, expected_return REAL, beta REAL, sector TEXT,
    PRIMARY KEY (asof_date, ticker)
);
"""


def latest_asof() -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT MAX(asof_date) d FROM scores").fetchone()
    return row["d"] if row else None


def get_scores() -> pd.DataFrame:
    """ticker -> {sector, score}. Uses combined_scores.combined if present, else composite."""
    asof = latest_asof()
    if not asof:
        raise RuntimeError("no scores — run Layers 2/3 first")
    with get_conn() as conn:
        comb = pd.read_sql_query(
            "SELECT ticker, sector, combined AS score FROM combined_scores WHERE asof_date=?",
            conn, params=(asof,))
        if comb.empty:
            comb = pd.read_sql_query(
                "SELECT ticker, sector, composite AS score FROM scores WHERE asof_date=?",
                conn, params=(asof,))
    return comb.set_index("ticker")


def expected_return(score: float) -> float:
    """Linear map: score 100 -> +r100/yr, score 0 -> r0/yr."""
    r100 = float(cfg.get("portfolio.expected_return.score_100_return", 0.15))
    r0 = float(cfg.get("portfolio.expected_return.score_0_return", -0.15))
    return r0 + (score / 100.0) * (r100 - r0)


def select_candidates(n: int | None = None) -> tuple[list[str], list[str]]:
    """Top n by score -> longs; bottom n -> shorts."""
    n = n or int(cfg.get("analysis.candidates_per_side", 20))
    s = get_scores().sort_values("score", ascending=False)
    longs = list(s.head(n).index)
    shorts = list(s.tail(n).index)
    return longs, shorts


def store_target(method: str, weights: dict[str, float], betas: dict[str, float],
                 scores: pd.DataFrame) -> None:
    asof = latest_asof()
    ensure_tables(_SCHEMA)
    with get_conn() as conn:
        conn.execute("DELETE FROM target_portfolio WHERE asof_date=?", (asof,))
        rows = []
        for t, w in weights.items():
            if abs(w) < 1e-9:
                continue
            sc = float(scores.loc[t, "score"]) if t in scores.index else None
            rows.append((asof, t, "long" if w > 0 else "short", w, method,
                         expected_return(sc) if sc is not None else None,
                         betas.get(t), scores.loc[t, "sector"] if t in scores.index else None))
        conn.executemany(
            "INSERT INTO target_portfolio (asof_date,ticker,side,weight,method,expected_return,beta,sector) "
            "VALUES (?,?,?,?,?,?,?,?)", rows)
    log.info("Stored %d target positions (method=%s)", len(rows), method)


def summary(weights: dict[str, float], betas: dict[str, float], scores: pd.DataFrame) -> dict:
    long_g = sum(w for w in weights.values() if w > 0)
    short_g = -sum(w for w in weights.values() if w < 0)
    net_beta = sum(w * betas.get(t, 1.0) for t, w in weights.items())
    sector_net: dict[str, float] = {}
    for t, w in weights.items():
        if t in scores.index:
            sec = scores.loc[t, "sector"]
            sector_net[sec] = sector_net.get(sec, 0.0) + w
    return {
        "n_long": sum(1 for w in weights.values() if w > 0),
        "n_short": sum(1 for w in weights.values() if w < 0),
        "long_gross": round(long_g, 4), "short_gross": round(short_g, 4),
        "gross": round(long_g + short_g, 4), "net": round(long_g - short_g, 4),
        "net_beta": round(net_beta, 4),
        "max_sector_net": round(max((abs(v) for v in sector_net.values()), default=0), 4),
    }
