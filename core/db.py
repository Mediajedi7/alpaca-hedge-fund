"""SQLite access. WAL mode + busy_timeout so the dashboard can read while the
scoring/execution jobs write concurrently (single-file SQLite would otherwise lock)."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from core.config import ROOT, cfg

DB_PATH = ROOT / cfg.get("data.db_path", "cache/meridian.db")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Transactional connection context manager (commits on success, rolls back on error)."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_tables(*create_statements: str) -> None:
    """Idempotently create tables/indexes. Each module passes its own DDL."""
    with get_conn() as conn:
        for stmt in create_statements:
            conn.executescript(stmt)


def add_columns_if_missing(table: str, columns: dict[str, str]) -> None:
    """Idempotent lightweight migration: ALTER TABLE ADD COLUMN for any missing column."""
    with get_conn() as conn:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for col, coltype in columns.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")


def set_meta(key: str, value: str) -> None:
    ensure_tables(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);"
    )
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO meta(key, value, updated_at) VALUES(?,?,datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at;",
            (key, value),
        )


def get_meta(key: str) -> str | None:
    ensure_tables(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);"
    )
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None
