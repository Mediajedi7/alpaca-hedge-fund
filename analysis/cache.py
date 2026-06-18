"""TTL-based analysis cache. Keyed by (analyzer, ticker, artifact_id) so re-running
the same artifact is a free cache hit. artifact_id should encode the input version
(e.g. latest period_end, 10-K accession, or a hash of the Form 4 rows)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from core.config import cfg
from core.db import ensure_tables, get_conn
from core.log import get_logger

log = get_logger("analysis_cache")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_results (
    analyzer    TEXT,
    ticker      TEXT,
    artifact_id TEXT,
    result      TEXT,        -- JSON
    created_at  TEXT,
    PRIMARY KEY (analyzer, ticker, artifact_id)
);
CREATE INDEX IF NOT EXISTS idx_analysis_ticker ON analysis_results(ticker);
"""


def artifact_hash(*parts) -> str:
    """Stable short id from arbitrary inputs."""
    blob = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _ttl_days() -> int:
    return int(cfg.get("analysis.cache_ttl_days", 30))


def get(analyzer: str, ticker: str, artifact_id: str) -> dict | None:
    ensure_tables(_SCHEMA)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT result, created_at FROM analysis_results "
            "WHERE analyzer=? AND ticker=? AND artifact_id=?",
            (analyzer, ticker, artifact_id),
        ).fetchone()
    if not row:
        return None
    age = datetime.now(timezone.utc) - datetime.fromisoformat(row["created_at"])
    if age > timedelta(days=_ttl_days()):
        return None  # expired (lazy eviction below)
    return json.loads(row["result"])


def put(analyzer: str, ticker: str, artifact_id: str, result: dict) -> None:
    ensure_tables(_SCHEMA)
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO analysis_results (analyzer,ticker,artifact_id,result,created_at) "
            "VALUES (?,?,?,?,?)",
            (analyzer, ticker, artifact_id, json.dumps(result),
             datetime.now(timezone.utc).isoformat()),
        )


def evict_expired() -> int:
    ensure_tables(_SCHEMA)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_ttl_days())).isoformat()
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM analysis_results WHERE created_at < ?", (cutoff,))
        return cur.rowcount


def all_for_ticker(ticker: str) -> dict[str, dict]:
    """Latest cached result per analyzer for a ticker (used by report/sector/combine)."""
    ensure_tables(_SCHEMA)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT analyzer, result, created_at FROM analysis_results WHERE ticker=? "
            "ORDER BY created_at DESC", (ticker,)
        ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        if r["analyzer"] not in out:  # newest first
            out[r["analyzer"]] = json.loads(r["result"])
    return out
