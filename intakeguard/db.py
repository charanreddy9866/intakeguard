"""SQLite access. One connection per request or worker run; never shared across threads."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from intakeguard.config import get_settings

SQL_DIR = Path(__file__).resolve().parent / "sql"
_SETUP_ATTEMPTS = 50


def connect(path: str | None = None) -> sqlite3.Connection:
    """Open a connection with WAL, a busy timeout and foreign keys, retrying while a new file is set up."""
    path = path or get_settings().db_path
    for attempt in range(_SETUP_ATTEMPTS):
        conn = sqlite3.connect(path, timeout=5.0, isolation_level=None, check_same_thread=False)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            return conn
        except sqlite3.OperationalError as exc:
            conn.close()
            if "locked" not in str(exc) or attempt == _SETUP_ATTEMPTS - 1:
                raise
            time.sleep(0.05)
    raise RuntimeError("unreachable")


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables and load the demo seed. Safe to call repeatedly and concurrently."""
    script = (SQL_DIR / "schema.sql").read_text(encoding="utf-8") + (SQL_DIR / "seed.sql").read_text(encoding="utf-8")
    for attempt in range(_SETUP_ATTEMPTS):
        try:
            conn.execute("BEGIN IMMEDIATE")
            for statement in _split(script):
                conn.execute(statement)
            conn.execute("COMMIT")
            return
        except sqlite3.OperationalError as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            if "locked" not in str(exc) or attempt == _SETUP_ATTEMPTS - 1:
                raise
            time.sleep(0.05)


def _split(script: str) -> list[str]:
    lines = [line for line in script.splitlines() if not line.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def audit(conn: sqlite3.Connection, tenant: str, document_id: str, event: str, actor: str, **detail) -> None:
    conn.execute(
        "INSERT INTO audit_log (tenant, document_id, event, actor, detail) VALUES (?, ?, ?, ?, ?)",
        (tenant, document_id, event, actor, json.dumps(detail, sort_keys=True)),
    )


def valid_claimant_ids(conn: sqlite3.Connection, tenant: str) -> set[str]:
    rows = conn.execute("SELECT claimant_id FROM claimants WHERE tenant = ?", (tenant,))
    return {r["claimant_id"] for r in rows}
