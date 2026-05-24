"""HealingRecorder — persists every heal attempt to SQLite for metrics and audit."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oapw.core.config import get_config


_DDL = """
CREATE TABLE IF NOT EXISTS healing_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL    NOT NULL,
    intent      TEXT    NOT NULL,
    page_url    TEXT    NOT NULL,
    original_locator TEXT,
    healed_locator   TEXT,
    strategy    TEXT    NOT NULL,
    success     INTEGER NOT NULL,
    confidence  REAL    NOT NULL,
    reasoning   TEXT
);
CREATE INDEX IF NOT EXISTS idx_heal_ts    ON healing_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_heal_strat ON healing_events(strategy);
"""


@dataclass
class HealingEvent:
    intent: str
    page_url: str
    original_locator: str
    healed_locator: str | None
    strategy: str
    success: bool
    confidence: float
    reasoning: str = ""
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.time()


class HealingRecorder:
    def __init__(self, db_path: Path | None = None) -> None:
        cfg = get_config()
        cfg.ensure_dirs()
        self._db_path = db_path or (cfg.data_dir / "healing.db")
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)

    def record(self, event: HealingEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO healing_events
                   (timestamp, intent, page_url, original_locator, healed_locator,
                    strategy, success, confidence, reasoning)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.timestamp, event.intent, event.page_url,
                    event.original_locator, event.healed_locator,
                    event.strategy, int(event.success), event.confidence, event.reasoning,
                ),
            )

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM healing_events").fetchone()[0]
            successes = conn.execute(
                "SELECT COUNT(*) FROM healing_events WHERE success = 1"
            ).fetchone()[0]
            by_strategy = conn.execute(
                """SELECT strategy, COUNT(*) as cnt,
                          SUM(success) as wins
                   FROM healing_events
                   GROUP BY strategy
                   ORDER BY cnt DESC"""
            ).fetchall()

        return {
            "total": total,
            "successes": successes,
            "success_rate": round(successes / total, 3) if total else 0.0,
            "by_strategy": [
                {"strategy": r[0], "attempts": r[1], "successes": r[2]}
                for r in by_strategy
            ],
        }

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT timestamp, intent, strategy, success, confidence, reasoning
                   FROM healing_events ORDER BY timestamp DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "timestamp": r[0], "intent": r[1], "strategy": r[2],
                "success": bool(r[3]), "confidence": r[4], "reasoning": r[5],
            }
            for r in rows
        ]
