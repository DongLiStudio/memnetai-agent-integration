"""Cross-platform configuration for the local integration runtime."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Mapping


DASHBOARD_URL = "https://dashboard.memnetai.com"


def _data_home() -> Path:
    override = os.environ.get("MEMNETAI_INTEGRATION_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "MemNetAI"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MemNetAI"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "memnetai"


@dataclass(frozen=True, slots=True)
class IntegrationDefaults:
    memory_agent_name: str = "personal-agent"
    namespace: str = "default"
    idle_timeout_minutes: int = 10
    max_messages: int = 32
    recall_timeout_seconds: float = 4.0
    base_url: str = "https://api.memnetai.com"
    database_path: Path | None = None

    def __post_init__(self) -> None:
        if self.database_path is None:
            object.__setattr__(self, "database_path", _data_home() / "state.sqlite3")


def load_config(path: Path | None = None, environ: Mapping[str, str] | None = None) -> IntegrationDefaults:
    """Load non-secret JSON configuration, with environment variables taking precedence."""
    env = environ or os.environ
    config_path = path or Path(env.get("MEMNETAI_INTEGRATION_CONFIG", _data_home() / "config.json"))
    values: dict[str, Any] = {}
    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Configuration must be a JSON object: {config_path}")
        values.update(raw)

    mapping = {
        "MEMNETAI_MEMORY_AGENT_NAME": ("memory_agent_name", str),
        "MEMNETAI_NAMESPACE": ("namespace", str),
        "MEMNETAI_IDLE_TIMEOUT_MINUTES": ("idle_timeout_minutes", int),
        "MEMNETAI_MAX_MESSAGES": ("max_messages", int),
        "MEMNETAI_RECALL_TIMEOUT_SECONDS": ("recall_timeout_seconds", float),
        "MEMNETAI_BASE_URL": ("base_url", str),
        "MEMNETAI_DATABASE_PATH": ("database_path", Path),
    }
    for env_name, (field_name, convert) in mapping.items():
        if env_name in env:
            values[field_name] = convert(env[env_name])
    allowed = {field.name for field in fields(IntegrationDefaults)}
    values = {key: value for key, value in values.items() if key in allowed}
    if "database_path" in values and values["database_path"] is not None:
        values["database_path"] = Path(values["database_path"]).expanduser()
    result = IntegrationDefaults(**values)
    if result.idle_timeout_minutes <= 0 or result.max_messages <= 0 or result.recall_timeout_seconds <= 0:
        raise ValueError("Timeout and threshold values must be positive")
    return result


def default_config_path(environ: Mapping[str, str] | None = None) -> Path:
    env = environ or os.environ
    return Path(env.get("MEMNETAI_INTEGRATION_CONFIG", _data_home() / "config.json"))


def save_config(config: IntegrationDefaults, path: Path | None = None) -> Path:
    target = path or default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(public_config(config), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return target


def public_config(config: IntegrationDefaults) -> dict[str, Any]:
    """Return a JSON-safe view; API keys intentionally are not part of this model."""
    result = asdict(config)
    result["database_path"] = str(result["database_path"])
    return result
