"""L2 SQLite disk cache — persistent across runs, per-project, 1–5ms lookup."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


_DDL = """
CREATE TABLE IF NOT EXISTS cache (
    key       TEXT PRIMARY KEY,
    value     TEXT NOT NULL,
    expires_at REAL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at);
"""


class L2Cache:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._hits = 0
        self._misses = 0
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)

    def get(self, key: str) -> Any | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            self._misses += 1
            return None
        value_json, expires_at = row
        if expires_at is not None and time.time() > expires_at:
            self.delete(key)
            self._misses += 1
            return None
        self._hits += 1
        return json.loads(value_json)

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        expires_at = time.time() + ttl if ttl is not None else None
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO cache (key, value, expires_at, created_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                       value = excluded.value,
                       expires_at = excluded.expires_at,
                       created_at = excluded.created_at""",
                (key, json.dumps(value), expires_at, time.time()),
            )

    def delete(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))

    def prune(self) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM cache WHERE expires_at IS NOT NULL AND expires_at < ?",
                (time.time(),),
            )
            return cur.rowcount

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM cache")
        self._hits = 0
        self._misses = 0

    def size(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "rows": self.size(),
            "db_path": str(self._db_path),
        }
