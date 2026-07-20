from __future__ import annotations

from pathlib import Path

from .base import (
    AdapterResult, command_exists, home_from_env, hook_command, merge_hook,
    read_json_object, write_json_atomic,
)
from .codex import CodexAdapter


class WorkBuddyAdapter(CodexAdapter):
    name = "workbuddy"

    @property
    def config_path(self) -> Path:
        return home_from_env("WORKBUDDY_HOME", ".workbuddy") / "settings.json"

    def detect(self) -> bool:
        return command_exists("workbuddy", "workbuddy.exe") or self.config_path.parent.exists()

    def install(self, executable: Path, *, dry_run: bool = False) -> AdapterResult:
        config = read_json_object(self.config_path)
        before = hook_command(executable, "before")
        after = hook_command(executable, "after")
        for item in (before, after):
            item.pop("commandWindows", None)
            item.pop("statusMessage", None)
        changed = merge_hook(config, "UserPromptSubmit", before)
        changed |= merge_hook(config, "Stop", after)
        if changed and not dry_run:
            write_json_atomic(self.config_path, config)
        return AdapterResult(self.name, self.detect(), not dry_run, not dry_run, "native-hooks",
                             str(self.config_path),
                             "updated" if changed else "already installed")

    def verify(self, executable: Path) -> AdapterResult:
        result = super().verify(executable)
        return AdapterResult(self.name, result.detected, result.installed, result.verified,
                             result.mode, result.config_path, result.detail)

    def uninstall(self, executable: Path, *, dry_run: bool = False) -> AdapterResult:
        result = super().uninstall(executable, dry_run=dry_run)
        return AdapterResult(self.name, result.detected, result.installed, result.verified,
                             result.mode, result.config_path, result.detail)
