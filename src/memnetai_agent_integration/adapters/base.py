from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


MARKER = "memnetai-integration"


@dataclass(frozen=True, slots=True)
class AdapterResult:
    host: str
    detected: bool
    installed: bool
    verified: bool
    mode: str
    config_path: str | None = None
    detail: str = ""


class HostAdapter(Protocol):
    name: str

    def detect(self) -> bool: ...
    def install(self, executable: Path, *, dry_run: bool = False) -> AdapterResult: ...
    def verify(self, executable: Path) -> AdapterResult: ...
    def uninstall(self, executable: Path, *, dry_run: bool = False) -> AdapterResult: ...


def command_exists(*names: str) -> bool:
    return any(shutil.which(name) for name in names)


def home_from_env(variable: str, fallback: str) -> Path:
    value = os.environ.get(variable)
    return Path(value).expanduser() if value else Path.home() / fallback


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"配置根节点必须是 JSON object: {path}")
    return value


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".memnetai.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def hook_command(executable: Path, event: str) -> dict[str, Any]:
    return {
        "type": "command",
        "command": f'"{executable}" hook-{event}',
        "commandWindows": f'"{executable}" hook-{event}',
        "timeout": 5 if event == "before" else 15,
        "statusMessage": "MemNetAI recall" if event == "before" else "MemNetAI capture",
    }


def merge_hook(config: dict[str, Any], event: str, command: dict[str, Any]) -> bool:
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks 必须是 JSON object")
    groups = hooks.setdefault(event, [])
    if not isinstance(groups, list):
        raise ValueError(f"hooks.{event} 必须是数组")
    managed_fragment = "memnetai-integration"
    for group in groups:
        if not isinstance(group, dict):
            continue
        for item in group.get("hooks", []):
            if isinstance(item, dict) and managed_fragment in str(item.get("command", "")):
                if item != command:
                    item.clear()
                    item.update(command)
                    return True
                return False
    groups.append({"hooks": [command]})
    return True


def remove_managed_hooks(config: dict[str, Any]) -> bool:
    changed = False
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept = []
        for group in groups:
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                original = group["hooks"]
                filtered = [
                    item for item in original
                    if not (isinstance(item, dict) and MARKER in str(item.get("command", "")))
                ]
                if len(filtered) != len(original):
                    changed = True
                    group = dict(group)
                    group["hooks"] = filtered
                if not filtered:
                    continue
            kept.append(group)
        hooks[event] = kept
    return changed
