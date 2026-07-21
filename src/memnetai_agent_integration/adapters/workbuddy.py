from __future__ import annotations

from pathlib import Path

from .base import (
    AdapterResult, command_exists, home_from_env, hook_command, merge_direct_hook,
    read_json_object, remove_direct_managed_hooks, remove_managed_hooks, write_json_atomic,
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
        # Migrate the invalid pre-0.2 nested user-settings shape without touching user hooks.
        changed = remove_managed_hooks(config)
        nested = config.get("hooks")
        if isinstance(nested, dict) and all(
            isinstance(groups, list) and not groups for groups in nested.values()
        ):
            config.pop("hooks")
            changed = True
        before = hook_command(executable, "before", self.name)
        after = hook_command(executable, "after", self.name)
        start = hook_command(executable, "session-start", self.name)
        for item in (before, after, start):
            item.pop("commandWindows", None)
            item.pop("statusMessage", None)
        changed |= merge_direct_hook(config, "UserPromptSubmit", before)
        changed |= merge_direct_hook(config, "Stop", after)
        changed |= merge_direct_hook(config, "SessionStart", start)
        if changed and not dry_run:
            write_json_atomic(self.config_path, config)
        return AdapterResult(self.name, self.detect(), not dry_run, not dry_run, "native-hooks",
                             str(self.config_path),
                             "updated" if changed else "already installed")

    def verify(self, executable: Path) -> AdapterResult:
        try:
            config = read_json_object(self.config_path)
            ok = all(event in config and isinstance(config[event], list)
                     for event in ("SessionStart", "UserPromptSubmit", "Stop"))
            # A nested `hooks` object is plugin syntax, not WorkBuddy user-settings syntax.
            ok = ok and all("memnetai-integration" in str(config[event]) for event in
                            ("SessionStart", "UserPromptSubmit", "Stop"))
        except (OSError, ValueError):
            ok = False
        return AdapterResult(self.name, self.detect(), ok, ok, "native-hooks",
                             str(self.config_path), "hook configuration found" if ok else "missing")

    def uninstall(self, executable: Path, *, dry_run: bool = False) -> AdapterResult:
        config = read_json_object(self.config_path)
        changed = remove_direct_managed_hooks(config)
        if changed and not dry_run:
            write_json_atomic(self.config_path, config)
        return AdapterResult(self.name, self.detect(), False, not changed or not dry_run,
                             "native-hooks", str(self.config_path),
                             "removed" if changed else "absent")
