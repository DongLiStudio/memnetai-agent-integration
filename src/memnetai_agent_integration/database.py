import sqlite3
from contextlib import closing
from pathlib import Path


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
    batch_id TEXT,
    sequence_number INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    memory_status TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    status TEXT NOT NULL,
    trigger_reason TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_flush
ON sessions (pending_count, next_flush_at);

CREATE INDEX IF NOT EXISTS idx_messages_session_status
ON messages (session_id, memory_status, sequence_number);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize(path: Path) -> None:
    with closing(connect(path)) as connection:
        with connection:
            connection.executescript(SCHEMA)
