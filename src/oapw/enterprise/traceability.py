"""Traceability store — bi-directional links between tests, Jira tickets, and Confluence pages.

SQLite at .oapw/traceability.db.  Two tables:
  traceability      — one row per test file
  jira_test_index   — inverted index for ticket → test lookups
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS traceability (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    test_path    TEXT NOT NULL,
    jira_ids     TEXT NOT NULL DEFAULT '[]',
    confluence_ids TEXT NOT NULL DEFAULT '[]',
    conf_versions  TEXT NOT NULL DEFAULT '{}',
    generated_at TEXT NOT NULL,
    UNIQUE(test_path)
);
CREATE INDEX IF NOT EXISTS idx_tr_test ON traceability(test_path);

CREATE TABLE IF NOT EXISTS jira_test_index (
    jira_key  TEXT NOT NULL,
    test_path TEXT NOT NULL,
    PRIMARY KEY (jira_key, test_path)
);
CREATE INDEX IF NOT EXISTS idx_jti_jira ON jira_test_index(jira_key);
"""


@dataclass
class TraceabilityRecord:
    test_path: str
    jira_ids: list[str]
    confluence_ids: list[str]
    conf_versions: dict[str, int]
    generated_at: str


class TraceabilityStore:
    """Persists and queries test ↔ ticket ↔ Confluence-page links."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        con = sqlite3.connect(str(self._db_path))
        con.execute("PRAGMA journal_mode=WAL")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _init_db(self) -> None:
        with self._conn() as con:
            con.executescript(_SCHEMA)

    def link_test(
        self,
        test_path: str,
        jira_ids: list[str],
        confluence_ids: list[str],
        conf_versions: dict[str, int] | None = None,
        generated_at: str | None = None,
    ) -> None:
        """Record or update traceability links for a test file."""
        from datetime import datetime, timezone
        ts = generated_at or datetime.now(tz=timezone.utc).isoformat()
        with self._conn() as con:
            con.execute(
                """INSERT INTO traceability
                       (test_path, jira_ids, confluence_ids, conf_versions, generated_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(test_path) DO UPDATE SET
                       jira_ids=excluded.jira_ids,
                       confluence_ids=excluded.confluence_ids,
                       conf_versions=excluded.conf_versions,
                       generated_at=excluded.generated_at""",
                (
                    test_path,
                    json.dumps(jira_ids),
                    json.dumps(confluence_ids),
                    json.dumps(conf_versions or {}),
                    ts,
                ),
            )
            # Rebuild jira → test index for this test
            con.execute("DELETE FROM jira_test_index WHERE test_path=?", (test_path,))
            con.executemany(
                "INSERT OR IGNORE INTO jira_test_index VALUES (?,?)",
                [(key, test_path) for key in jira_ids],
            )

    def tests_for_ticket(self, jira_key: str) -> list[str]:
        """Return test file paths linked to a Jira ticket."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT test_path FROM jira_test_index WHERE jira_key=?",
                (jira_key,),
            ).fetchall()
        return [r[0] for r in rows]

    def record_for_test(self, test_path: str) -> TraceabilityRecord | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT test_path, jira_ids, confluence_ids, conf_versions, generated_at "
                "FROM traceability WHERE test_path=?",
                (test_path,),
            ).fetchone()
        if not row:
            return None
        return TraceabilityRecord(
            test_path=row[0],
            jira_ids=json.loads(row[1]),
            confluence_ids=json.loads(row[2]),
            conf_versions=json.loads(row[3]),
            generated_at=row[4],
        )

    def all_records(self) -> list[TraceabilityRecord]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT test_path, jira_ids, confluence_ids, conf_versions, generated_at "
                "FROM traceability ORDER BY generated_at DESC"
            ).fetchall()
        return [
            TraceabilityRecord(
                test_path=r[0],
                jira_ids=json.loads(r[1]),
                confluence_ids=json.loads(r[2]),
                conf_versions=json.loads(r[3]),
                generated_at=r[4],
            )
            for r in rows
        ]

    def coverage_summary(self) -> dict:
        """Return aggregate coverage stats."""
        records = self.all_records()
        jira_covered: set[str] = set()
        for r in records:
            jira_covered.update(r.jira_ids)
        return {
            "total_tests_traced": len(records),
            "jira_tickets_covered": len(jira_covered),
            "jira_keys": sorted(jira_covered),
        }

    def clear(self) -> None:
        with self._conn() as con:
            con.execute("DELETE FROM traceability")
            con.execute("DELETE FROM jira_test_index")
