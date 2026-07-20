"""Persistent ownership manifest for reversible installation writes."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    path: str
    created: bool
    backup_path: str | None = None


@dataclass(slots=True)
class InstallManifest:
    version: int = 1
    scheduler: str | None = None
    scheduler_id: str | None = None
    entries: list[ManifestEntry] = field(default_factory=list)

    def record(self, entry: ManifestEntry) -> None:
        self.entries = [item for item in self.entries if item.path != entry.path]
        self.entries.append(entry)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n"
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    @classmethod
    def load(cls, path: Path) -> "InstallManifest":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            version=int(data["version"]),
            scheduler=data.get("scheduler"),
            scheduler_id=data.get("scheduler_id"),
            entries=[ManifestEntry(**entry) for entry in data.get("entries", [])],
        )
