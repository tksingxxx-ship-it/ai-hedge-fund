"""SQLite storage for office workflow state.

Financial positions, cash, and NAV are not stored here. Those stay in the
engine ledger. This database holds missions, tasks, events, approvals, and
job metadata.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from office.config import Config

_LOCK = threading.Lock()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    channel TEXT NOT NULL,
    source TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    state TEXT,
    message TEXT NOT NULL,
    payload_json TEXT,
    execution_mode TEXT
);
CREATE INDEX IF NOT EXISTS events_entity ON events(entity_type, entity_id, id);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    channel TEXT NOT NULL,
    author TEXT NOT NULL,
    mission_id TEXT,
    task_id TEXT,
    body TEXT NOT NULL,
    execution_mode TEXT
);
CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    brief TEXT NOT NULL,
    universe_json TEXT NOT NULL,
    universe_preset TEXT,
    strategies_json TEXT NOT NULL,
    risk_json TEXT NOT NULL,
    capital REAL NOT NULL,
    rebalance TEXT NOT NULL,
    benchmark TEXT NOT NULL,
    as_of TEXT NOT NULL,
    status TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    budget_json TEXT NOT NULL,
    summary_json TEXT,
    error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    parent_id TEXT,
    agent TEXT NOT NULL,
    strategy TEXT,
    kind TEXT NOT NULL,
    ticker TEXT,
    status TEXT NOT NULL,
    depends_on_json TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    max_attempts INTEGER NOT NULL,
    depth INTEGER NOT NULL,
    payload_json TEXT,
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS tasks_mission ON tasks(mission_id, status);
CREATE TABLE IF NOT EXISTS agent_runtime (
    agent TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    task_id TEXT,
    detail TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cio_decisions (
    id TEXT PRIMARY KEY,
    mission_id TEXT,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    request_json TEXT NOT NULL,
    result_ref TEXT,
    result_json TEXT,
    progress_json TEXT,
    error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    execution_mode TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    fund_name TEXT NOT NULL,
    action TEXT NOT NULL,
    session TEXT,
    plan_hash TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    consumed_at TEXT
);
CREATE TABLE IF NOT EXISTS paper_meta (
    name TEXT PRIMARY KEY,
    directory TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(config: Config) -> sqlite3.Connection:
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(config: Config) -> None:
    with _LOCK:
        conn = connect(config)
        try:
            conn.executescript(_SCHEMA)
            row = conn.execute("SELECT version FROM schema_migrations WHERE version=1").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (1, ?)",
                    (utcnow(),),
                )
            conn.commit()
        finally:
            conn.close()


@contextmanager
def transaction(config: Config) -> Iterator[sqlite3.Connection]:
    with _LOCK:
        conn = connect(config)
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def loads(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)


def row_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def recover_inflight(config: Config) -> int:
    """Mark work that was in flight when the process died.

    The engine ledger is not touched. A paper tick that crashed mid-fill
    is still caught by the engine's next reconciliation.
    """
    reason = "interrupted by process restart"
    stamp = utcnow()
    with transaction(config) as conn:
        jobs = conn.execute("SELECT id FROM jobs WHERE status='running'").fetchall()
        missions = conn.execute("SELECT id FROM missions WHERE status='running'").fetchall()
        tasks = conn.execute(
            "SELECT id, agent FROM tasks WHERE status IN ('working', 'reviewing', 'waiting')"
        ).fetchall()
        conn.execute(
            "UPDATE jobs SET status='interrupted', error=?, updated_at=? WHERE status='running'",
            (reason, stamp),
        )
        conn.execute(
            "UPDATE missions SET status='interrupted', error=?, updated_at=? WHERE status='running'",
            (reason, stamp),
        )
        conn.execute(
            """UPDATE tasks SET status='failed', error=?, finished_at=?
               WHERE status IN ('working', 'reviewing', 'waiting')""",
            (reason, stamp),
        )
        conn.execute(
            """UPDATE agent_runtime SET state='failed', detail=?, updated_at=?
               WHERE state IN ('working', 'reviewing', 'waiting')""",
            (reason, stamp),
        )
        for job in jobs:
            _insert_event(conn, channel="system", source="office", entity_type="job",
                          entity_id=job["id"], state="interrupted", message=reason, execution_mode=None)
        for mission in missions:
            _insert_event(conn, channel="system", source="office", entity_type="mission",
                          entity_id=mission["id"], state="interrupted", message=reason, execution_mode=None)
        for task in tasks:
            _insert_event(conn, channel="system", source=task["agent"], entity_type="task",
                          entity_id=task["id"], state="failed", message=reason, execution_mode=None)
        return len(jobs) + len(missions) + len(tasks)


def _insert_event(conn, *, channel, source, message, entity_type=None, entity_id=None,
                  state=None, payload=None, execution_mode=None) -> dict:
    from office.redact import redact
    message = redact(message)
    if payload is not None:
        payload = json.loads(redact(json.dumps(payload, default=str)))
    stamp = utcnow()
    cur = conn.execute(
        """INSERT INTO events(ts, channel, source, entity_type, entity_id, state, message, payload_json, execution_mode)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (stamp, channel, source, entity_type, entity_id, state, message,
         dumps(payload) if payload is not None else None, execution_mode),
    )
    event = {
        "id": cur.lastrowid, "ts": stamp, "channel": channel, "source": source,
        "entity_type": entity_type, "entity_id": entity_id, "state": state,
        "message": message, "payload": payload, "execution_mode": execution_mode,
    }
    from office.bus import publish
    publish(event)
    return event


def add_event(config: Config, **kwargs) -> dict:
    with transaction(config) as conn:
        return _insert_event(conn, **kwargs)


def add_message(config: Config, *, channel: str, author: str, body: str,
                mission_id: str | None = None, task_id: str | None = None,
                execution_mode: str | None = None) -> dict:
    from office.redact import redact
    body = redact(body)
    stamp = utcnow()
    with transaction(config) as conn:
        cur = conn.execute(
            """INSERT INTO messages(ts, channel, author, mission_id, task_id, body, execution_mode)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (stamp, channel, author, mission_id, task_id, body, execution_mode),
        )
        return {"id": cur.lastrowid, "ts": stamp, "channel": channel, "author": author,
                "mission_id": mission_id, "task_id": task_id, "body": body,
                "execution_mode": execution_mode}


def set_agent_state(conn, agent: str, state: str, *, task_id: str | None = None, detail: str | None = None) -> None:
    conn.execute(
        """INSERT INTO agent_runtime(agent, state, task_id, detail, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(agent) DO UPDATE SET
             state=excluded.state, task_id=excluded.task_id, detail=excluded.detail, updated_at=excluded.updated_at""",
        (agent, state, task_id, detail, utcnow()),
    )


def get_setting(config: Config, key: str) -> str | None:
    conn = connect(config)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return None if row is None else row["value"]
    finally:
        conn.close()


def set_setting(config: Config, key: str, value: str) -> None:
    with transaction(config) as conn:
        conn.execute(
            """INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, value, utcnow()),
        )
