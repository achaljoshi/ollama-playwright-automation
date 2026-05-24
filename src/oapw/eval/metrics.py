"""Metrics collection for the framework self-evaluation suite.

Tracks per-run: resolution success rate, healing success rate, cache hit rate,
and latency percentiles (p50/p95). Persisted to .oapw/eval_metrics.db.
"""

from __future__ import annotations

import sqlite3
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from oapw.core.config import get_config


_DDL = """
CREATE TABLE IF NOT EXISTS eval_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    NOT NULL,
    timestamp   REAL    NOT NULL,
    page_name   TEXT    NOT NULL,
    intent      TEXT    NOT NULL,
    resolved    INTEGER NOT NULL,
    healed      INTEGER NOT NULL,
    from_cache  INTEGER NOT NULL,
    latency_ms  REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_run ON eval_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_ts  ON eval_runs(timestamp);
"""


@dataclass
class ResolutionRecord:
    page_name: str
    intent: str
    resolved: bool
    healed: bool = False
    from_cache: bool = False
    latency_ms: float = 0.0


@dataclass
class EvalReport:
    run_id: str
    total: int
    resolved: int
    healed: int
    cache_hits: int
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def resolution_rate(self) -> float:
        return round(self.resolved / self.total, 3) if self.total else 0.0

    @property
    def healing_rate(self) -> float:
        return round(self.healed / self.total, 3) if self.total else 0.0

    @property
    def cache_hit_rate(self) -> float:
        return round(self.cache_hits / self.total, 3) if self.total else 0.0

    @property
    def p50_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return round(statistics.median(self.latencies_ms), 1)

    @property
    def p95_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        sorted_lats = sorted(self.latencies_ms)
        idx = int(len(sorted_lats) * 0.95)
        return round(sorted_lats[min(idx, len(sorted_lats) - 1)], 1)

    def passed(self, min_resolution: float = 0.95) -> bool:
        return self.resolution_rate >= min_resolution

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total": self.total,
            "resolution_rate": self.resolution_rate,
            "healing_rate": self.healing_rate,
            "cache_hit_rate": self.cache_hit_rate,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
        }


class MetricsCollector:
    def __init__(self, db_path: Path | None = None) -> None:
        cfg = get_config()
        cfg.ensure_dirs()
        self._db_path = db_path or (cfg.data_dir / "eval_metrics.db")
        self._records: list[ResolutionRecord] = []
        self._run_id = f"run_{int(time.time())}"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)

    def record(self, rec: ResolutionRecord) -> None:
        self._records.append(rec)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO eval_runs
                   (run_id, timestamp, page_name, intent, resolved, healed, from_cache, latency_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self._run_id, time.time(), rec.page_name, rec.intent,
                    int(rec.resolved), int(rec.healed), int(rec.from_cache), rec.latency_ms,
                ),
            )

    def report(self) -> EvalReport:
        total = len(self._records)
        return EvalReport(
            run_id=self._run_id,
            total=total,
            resolved=sum(1 for r in self._records if r.resolved),
            healed=sum(1 for r in self._records if r.healed),
            cache_hits=sum(1 for r in self._records if r.from_cache),
            latencies_ms=[r.latency_ms for r in self._records],
        )

    def historical_summary(self, last_n_runs: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            run_ids = conn.execute(
                """SELECT DISTINCT run_id FROM eval_runs
                   ORDER BY timestamp DESC LIMIT ?""",
                (last_n_runs,),
            ).fetchall()

        summaries = []
        for (rid,) in run_ids:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT resolved, healed, from_cache, latency_ms FROM eval_runs WHERE run_id = ?",
                    (rid,),
                ).fetchall()
            total = len(rows)
            if total == 0:
                continue
            lats = [r[3] for r in rows]
            sorted_lats = sorted(lats)
            p95_idx = int(total * 0.95)
            summaries.append({
                "run_id": rid,
                "total": total,
                "resolution_rate": sum(r[0] for r in rows) / total,
                "healing_rate": sum(r[1] for r in rows) / total,
                "cache_hit_rate": sum(r[2] for r in rows) / total,
                "p50_ms": statistics.median(lats) if lats else 0.0,
                "p95_ms": sorted_lats[min(p95_idx, total - 1)] if lats else 0.0,
            })
        return summaries
