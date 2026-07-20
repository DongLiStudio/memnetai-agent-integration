from __future__ import annotations

from pathlib import Path

from .base import AdapterResult


PROMPT_MARKER_START = "<!-- memnetai-agent-integration:start -->"
PROMPT_MARKER_END = "<!-- memnetai-agent-integration:end -->"
PROMPT = f"""{PROMPT_MARKER_START}
每轮实质回答前，运行 `memnetai-integration hook-before` 并把返回的 memoryPrompt 作为仅本轮上下文；回答完成后把宿主提供的最终回答通过 `memnetai-integration hook-after` 记录。任何失败不得阻塞普通回答，并向用户显示命令返回的 notice。
{PROMPT_MARKER_END}"""


class GenericPromptAdapter:
    name = "generic-prompt"

    def __init__(self, target: Path | None = None) -> None:
        self.target = target

    def detect(self) -> bool:
        return self.target is not None

    def install(self, executable: Path, *, dry_run: bool = False) -> AdapterResult:
        if self.target is None:
            return AdapterResult(self.name, False, False, False, "manual-prompt", detail=PROMPT)
        existing = self.target.read_text(encoding="utf-8") if self.target.exists() else ""
        changed = PROMPT_MARKER_START not in existing
        if changed and not dry_run:
            self.target.parent.mkdir(parents=True, exist_ok=True)
            self.target.write_text(existing.rstrip() + "\n\n" + PROMPT + "\n", encoding="utf-8")
        return AdapterResult(self.name, True, not dry_run, not dry_run, "prompt-fallback",
                             str(self.target), "updated" if changed else "already installed")

    def verify(self, executable: Path) -> AdapterResult:
        ok = bool(self.target and self.target.exists() and
                  PROMPT_MARKER_START in self.target.read_text(encoding="utf-8"))
        return AdapterResult(self.name, self.detect(), ok, ok, "prompt-fallback",
                             str(self.target) if self.target else None)

    def uninstall(self, executable: Path, *, dry_run: bool = False) -> AdapterResult:
        if not self.target or not self.target.exists():
            return AdapterResult(self.name, self.detect(), False, True, "prompt-fallback")
        text = self.target.read_text(encoding="utf-8")
        start = text.find(PROMPT_MARKER_START)
        end = text.find(PROMPT_MARKER_END)
        changed = start >= 0 and end >= start
        if changed and not dry_run:
            cleaned = text[:start] + text[end + len(PROMPT_MARKER_END):]
            self.target.write_text(cleaned.strip() + "\n", encoding="utf-8")
        return AdapterResult(self.name, True, False, True, "prompt-fallback",
                             str(self.target), "removed" if changed else "absent")
