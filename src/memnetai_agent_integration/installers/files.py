"""Atomic, backed-up file changes owned by an installation manifest."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from .manifest import InstallManifest, ManifestEntry


class AtomicFileManager:
    def __init__(self, backup_root: Path, manifest: InstallManifest) -> None:
        self.backup_root = backup_root
        self.manifest = manifest

    def write_text(self, path: Path, content: str, *, dry_run: bool = False) -> ManifestEntry:
        existing = next((entry for entry in self.manifest.entries if entry.path == str(path)), None)
        if existing is not None and path.exists() and path.read_text(encoding="utf-8") == content:
            return existing

        created = not path.exists()
        backup_path: Path | None = None
        if not created:
            backup_path = self.backup_root / f"{len(self.manifest.entries):04d}-{path.name}.bak"
        entry = ManifestEntry(str(path), created, str(backup_path) if backup_path else None)
        if dry_run:
            return entry

        path.parent.mkdir(parents=True, exist_ok=True)
        if backup_path is not None and existing is None:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_path)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        self.manifest.record(existing or entry)
        return existing or entry

    def restore_all(self, *, dry_run: bool = False) -> None:
        if dry_run:
            return
        for entry in reversed(self.manifest.entries):
            path = Path(entry.path)
            if entry.created:
                path.unlink(missing_ok=True)
            elif entry.backup_path:
                backup = Path(entry.backup_path)
                if backup.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(backup, path)
