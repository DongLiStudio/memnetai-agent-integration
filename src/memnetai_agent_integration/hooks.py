"""Normalize lifecycle payloads emitted by supported agent hosts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO


@dataclass(frozen=True, slots=True)
class HookMessage:
    host: str
    event: str
    session_id: str
    turn_id: str
    prompt: str = ""
    response: str = ""
    transcript_path: str | None = None

    def event_id(self, role: str, content: str) -> str:
        material = "\0".join((self.host, self.session_id, self.turn_id, self.event, role, content))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


def read_payload(stream: TextIO) -> dict[str, Any]:
    text = stream.read().strip()
    if not text:
        return {}
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Hook payload must be a JSON object")
    return value


def normalize(payload: dict[str, Any], *, event: str) -> HookMessage:
    raw_event = str(payload.get("hook_event_name", ""))
    transcript = _text(payload.get("transcript_path")) or None
    host = str(payload.get("host") or _host_from_event(raw_event, transcript)).lower()
    session_id = str(payload.get("session_id") or payload.get("thread_id") or "unknown")
    turn_id = str(payload.get("turn_id") or payload.get("task_id") or "")
    prompt = _text(
        payload.get("prompt") or payload.get("user_message") or payload.get("user_prompt")
    )
    response = _text(payload.get("last_assistant_message") or payload.get("assistant_response"))
    if event == "after" and not response and transcript:
        response = extract_last_assistant(Path(transcript))
    if not turn_id:
        turn_id = hashlib.sha256(
            "\0".join((session_id, prompt, response, raw_event or event)).encode("utf-8")
        ).hexdigest()[:24]
    return HookMessage(host, event, session_id, turn_id, prompt, response, transcript)


def extract_last_assistant(path: Path) -> str:
    """Best-effort reverse scan for WorkBuddy/CodeBuddy JSONL transcripts."""
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        found = _assistant_from_node(value)
        if found:
            return found
    return ""


def _assistant_from_node(node: Any) -> str:
    if isinstance(node, dict):
        role = str(node.get("role") or node.get("type") or "").lower()
        if role in {"assistant", "agent", "assistant_message"}:
            text = _content_text(node.get("content") or node.get("message") or node.get("text"))
            if text:
                return text
        for key in ("message", "payload", "data"):
            found = _assistant_from_node(node.get(key))
            if found:
                return found
    return ""


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return _content_text(value.get("text") or value.get("content"))
    if isinstance(value, list):
        parts = [_content_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    return ""


def _host_from_event(event: str, transcript_path: str | None = None) -> str:
    if event in {"pre_llm_call", "post_llm_call"}:
        return "hermes"
    path = (transcript_path or "").replace("\\", "/").lower()
    if "/.workbuddy/" in path or "/.codebuddy/" in path:
        return "workbuddy"
    return "workbuddy" if "codebuddy" in event.lower() else "codex"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
