from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def record(home: Path, host: str, event: str, session_id: str) -> None:
    path = home / "hook-health" / f"{host}-{event}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps({
            "host": host,
            "event": event,
            "session_id": session_id,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_host(home: Path, host: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for event in ("session-start", "before", "after"):
        path = home / "hook-health" / f"{host}-{event}.json"
        try:
            result[event] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            result[event] = None
    return result
