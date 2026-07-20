"""Transactional SQLite state for per-session buffers and durable batches."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    host TEXT NOT NULL,
    memory_agent_name TEXT NOT NULL DEFAULT 'personal-agent',
    namespace TEXT NOT NULL DEFAULT 'default',
    last_activity_at TEXT NOT NULL,
    next_flush_at TEXT NOT NULL,
    pending_count INTEGER NOT NULL DEFAULT 0,
    in_flight INTEGER NOT NULL DEFAULT 0,
    generation INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    batch_id TEXT REFERENCES batches(batch_id),
    sequence_number INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    memory_status TEXT NOT NULL DEFAULT 'pending',
    UNIQUE(session_id, sequence_number)
);
CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    status TEXT NOT NULL CHECK(status IN ('sealed','submitting','submitted','retry','complete','failed')),
    trigger_reason TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    next_retry_at TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    remote_task_id TEXT,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_flush ON sessions (pending_count, next_flush_at);
CREATE INDEX IF NOT EXISTS idx_messages_session_status ON messages (session_id, memory_status, sequence_number);
"""

BATCH_MIGRATIONS = {
    "created_at": "TEXT NOT NULL DEFAULT ''",
    "updated_at": "TEXT NOT NULL DEFAULT ''",
    "next_retry_at": "TEXT",
    "remote_task_id": "TEXT",
}


@dataclass(frozen=True, slots=True)
class MessageRecord:
    message_id: str
    session_id: str
    sequence_number: int
    role: str
    content: str
    created_at: str


@dataclass(frozen=True, slots=True)
class BatchRecord:
    batch_id: str
    session_id: str
    idempotency_key: str
    status: str
    trigger_reason: str
    retry_count: int
    remote_task_id: str | None = None


class ClosingConnection(sqlite3.Connection):
    """A connection whose context manager commits/rolls back *and* closes.

    sqlite3.Connection.__exit__ normally leaves the handle open, which is easy to
    miss and prevents immediate temporary-database cleanup on Windows.
    """

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        path, timeout=5, isolation_level=None, factory=ClosingConnection
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize(path: Path) -> None:
    with closing(connect(path)) as connection:
        connection.executescript(SCHEMA)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(batches)").fetchall()
        }
        for name, definition in BATCH_MIGRATIONS.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE batches ADD COLUMN {name} {definition}")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_batches_retry ON batches (status, next_retry_at)"
        )
        connection.execute("PRAGMA user_version=1")


def append_message(
    path: Path, *, session_id: str, host: str, role: str, content: str,
    memory_agent_name: str = "personal-agent", namespace: str = "default",
    idle_minutes: int = 10, message_id: str | None = None, created_at: str | None = None,
) -> MessageRecord:
    """Append atomically. A caller-provided event/message id makes host retries idempotent."""
    if role not in {"user", "assistant", "system"}:
        raise ValueError(f"Unsupported role: {role}")
    initialize(path)
    now = created_at or utc_now()
    due = (datetime.fromisoformat(now) + timedelta(minutes=idle_minutes)).isoformat()
    stable_id = message_id or str(uuid.uuid4())
    with closing(connect(path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute("SELECT * FROM messages WHERE message_id=?", (stable_id,)).fetchone()
        if existing:
            connection.commit()
            return MessageRecord(stable_id, existing["session_id"], existing["sequence_number"], existing["role"], existing["content"], existing["created_at"])
        connection.execute(
            """INSERT INTO sessions(session_id,host,memory_agent_name,namespace,last_activity_at,next_flush_at)
               VALUES(?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET
               host=excluded.host, memory_agent_name=excluded.memory_agent_name,
               namespace=excluded.namespace, last_activity_at=excluded.last_activity_at,
               next_flush_at=excluded.next_flush_at""",
            (session_id, host, memory_agent_name, namespace, now, due),
        )
        seq = connection.execute("SELECT COALESCE(MAX(sequence_number),0)+1 FROM messages WHERE session_id=?", (session_id,)).fetchone()[0]
        connection.execute(
            "INSERT INTO messages(message_id,session_id,sequence_number,role,content,created_at) VALUES(?,?,?,?,?,?)",
            (stable_id, session_id, seq, role, content, now),
        )
        connection.execute("UPDATE sessions SET pending_count=pending_count+1 WHERE session_id=?", (session_id,))
        connection.commit()
    return MessageRecord(stable_id, session_id, seq, role, content, now)


def due_sessions(path: Path, *, max_messages: int, now: str | None = None) -> list[str]:
    initialize(path)
    instant = now or utc_now()
    with closing(connect(path)) as connection:
        return [row[0] for row in connection.execute(
            "SELECT session_id FROM sessions WHERE in_flight=0 AND pending_count>0 AND (pending_count>=? OR next_flush_at<=?) ORDER BY next_flush_at",
            (max_messages, instant),
        )]


def seal_batch(path: Path, *, session_id: str, trigger_reason: str) -> BatchRecord | None:
    """Atomically freeze all currently pending messages into one idempotent batch."""
    initialize(path)
    now = utc_now()
    with closing(connect(path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute("SELECT message_id FROM messages WHERE session_id=? AND memory_status='pending' ORDER BY sequence_number", (session_id,)).fetchall()
        if not rows:
            connection.commit()
            return None
        ids = [row[0] for row in rows]
        key = hashlib.sha256((session_id + "\0" + "\0".join(ids)).encode()).hexdigest()
        batch_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "memnetai:" + key))
        connection.execute(
            "INSERT OR IGNORE INTO batches(batch_id,session_id,status,trigger_reason,idempotency_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (batch_id, session_id, "sealed", trigger_reason, key, now, now),
        )
        connection.executemany("UPDATE messages SET batch_id=?,memory_status='sealed' WHERE message_id=? AND memory_status='pending'", ((batch_id, mid) for mid in ids))
        changed = connection.total_changes
        connection.execute("UPDATE sessions SET pending_count=(SELECT COUNT(*) FROM messages WHERE session_id=? AND memory_status='pending'),in_flight=1,generation=generation+1 WHERE session_id=?", (session_id, session_id))
        row = connection.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        connection.commit()
    if not changed or row is None:
        return None
    return BatchRecord(row["batch_id"], row["session_id"], row["idempotency_key"], row["status"], row["trigger_reason"], row["retry_count"], row["remote_task_id"])


def batch_messages(path: Path, batch_id: str) -> list[MessageRecord]:
    with closing(connect(path)) as connection:
        rows = connection.execute("SELECT * FROM messages WHERE batch_id=? ORDER BY sequence_number", (batch_id,)).fetchall()
    return [MessageRecord(r["message_id"], r["session_id"], r["sequence_number"], r["role"], r["content"], r["created_at"]) for r in rows]


def mark_batch_submitting(path: Path, batch_id: str) -> bool:
    with closing(connect(path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute("UPDATE batches SET status='submitting',updated_at=? WHERE batch_id=? AND status IN ('sealed','retry')", (utc_now(), batch_id))
        connection.commit()
        return cursor.rowcount == 1


def mark_batch_submitted(path: Path, batch_id: str, remote_task_id: str | None = None) -> None:
    with closing(connect(path)) as connection:
        with connection:
            connection.execute("UPDATE batches SET status='submitted',remote_task_id=?,updated_at=?,last_error=NULL WHERE batch_id=?", (remote_task_id, utc_now(), batch_id))


def complete_batch(path: Path, batch_id: str) -> None:
    with closing(connect(path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT session_id FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        if not row:
            connection.rollback()
            raise KeyError(batch_id)
        connection.execute("UPDATE batches SET status='complete',updated_at=? WHERE batch_id=?", (utc_now(), batch_id))
        connection.execute("UPDATE messages SET memory_status='complete' WHERE batch_id=?", (batch_id,))
        connection.execute("UPDATE sessions SET in_flight=0 WHERE session_id=?", (row[0],))
        connection.commit()


def retry_batch(path: Path, batch_id: str, error: str, *, delay_seconds: int = 30, max_retries: int = 5) -> None:
    with closing(connect(path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT session_id,retry_count FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        if not row:
            connection.rollback()
            raise KeyError(batch_id)
        retries = row["retry_count"] + 1
        status = "failed" if retries >= max_retries else "retry"
        next_retry = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds * 2 ** (retries - 1))).isoformat() if status == "retry" else None
        connection.execute("UPDATE batches SET status=?,retry_count=?,next_retry_at=?,last_error=?,updated_at=? WHERE batch_id=?", (status, retries, next_retry, error[:1000], utc_now(), batch_id))
        if status == "failed":
            connection.execute("UPDATE sessions SET in_flight=0 WHERE session_id=?", (row["session_id"],))
        connection.commit()


def retryable_batches(path: Path, now: str | None = None) -> list[str]:
    with closing(connect(path)) as connection:
        return [row[0] for row in connection.execute("SELECT batch_id FROM batches WHERE status='retry' AND next_retry_at<=? ORDER BY next_retry_at", (now or utc_now(),))]


def get_batch(path: Path, batch_id: str) -> BatchRecord | None:
    initialize(path)
    with closing(connect(path)) as connection:
        row = connection.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
    if row is None:
        return None
    return BatchRecord(row["batch_id"], row["session_id"], row["idempotency_key"],
                       row["status"], row["trigger_reason"], row["retry_count"],
                       row["remote_task_id"])


def submitted_batches(path: Path) -> list[BatchRecord]:
    initialize(path)
    with closing(connect(path)) as connection:
        rows = connection.execute(
            "SELECT * FROM batches WHERE status='submitted' AND remote_task_id IS NOT NULL "
            "ORDER BY updated_at"
        ).fetchall()
    return [BatchRecord(row["batch_id"], row["session_id"], row["idempotency_key"],
                        row["status"], row["trigger_reason"], row["retry_count"],
                        row["remote_task_id"]) for row in rows]
