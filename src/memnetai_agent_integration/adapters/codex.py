from __future__ import annotations

from pathlib import Path

from .base import (
    AdapterResult,
    command_exists,
    home_from_env,
    hook_command,
    merge_hook,
    read_json_object,
    remove_managed_hooks,
    write_json_atomic,
)


class CodexAdapter:
    name = "codex"

    @property
    def config_path(self) -> Path:
        return home_from_env("CODEX_HOME", ".codex") / "hooks.json"

    def detect(self) -> bool:
        return command_exists("codex", "codex.exe") or self.config_path.parent.exists()

    def install(self, executable: Path, *, dry_run: bool = False) -> AdapterResult:
        config = read_json_object(self.config_path)
        changed = merge_hook(config, "UserPromptSubmit", hook_command(executable, "before"))
        changed |= merge_hook(config, "Stop", hook_command(executable, "after"))
        if changed and not dry_run:
            write_json_atomic(self.config_path, config)
        return AdapterResult(self.name, self.detect(), not dry_run, not dry_run, "native-hooks",
                             str(self.config_path), "updated" if changed else "already installed")

    def verify(self, executable: Path) -> AdapterResult:
        try:
            text = self.config_path.read_text(encoding="utf-8-sig")
            ok = "memnetai-integration" in text and "UserPromptSubmit" in text and "Stop" in text
        except OSError:
            ok = False
        return AdapterResult(self.name, self.detect(), ok, ok, "native-hooks",
                             str(self.config_path), "hook configuration found" if ok else "missing")

    def uninstall(self, executable: Path, *, dry_run: bool = False) -> AdapterResult:
        config = read_json_object(self.config_path)
        changed = remove_managed_hooks(config)
        if changed and not dry_run:
            write_json_atomic(self.config_path, config)
        return AdapterResult(self.name, self.detect(), False, not changed or not dry_run,
                             "native-hooks", str(self.config_path), "removed" if changed else "absent")
