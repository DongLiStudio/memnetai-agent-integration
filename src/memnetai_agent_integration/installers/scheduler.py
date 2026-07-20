"""Native per-user scheduler adapters for ``flush-due``."""

from __future__ import annotations

import plistlib
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

from .files import AtomicFileManager


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class Runner(Protocol):
    def __call__(self, args: Sequence[str], input_text: str | None = None) -> CommandResult: ...


def subprocess_runner(args: Sequence[str], input_text: str | None = None) -> CommandResult:
    result = subprocess.run(
        list(args), input=input_text, capture_output=True, text=True, check=False
    )
    return CommandResult(result.returncode, result.stdout, result.stderr)


@dataclass(frozen=True, slots=True)
class SchedulePlan:
    scheduler: str
    identifier: str
    files: tuple[Path, ...]
    commands: tuple[tuple[str, ...], ...]


class SchedulerError(RuntimeError):
    pass


class WindowsTaskScheduler:
    def __init__(self, runner: Runner = subprocess_runner, task_name: str = "MemNetAI Flush Due"):
        self.runner = runner
        self.task_name = task_name

    def plan(self, command: Sequence[str]) -> SchedulePlan:
        task_command = subprocess.list2cmdline(list(command))
        create = (
            "schtasks", "/Create", "/TN", self.task_name, "/SC", "MINUTE", "/MO", "1",
            "/TR", task_command, "/F",
        )
        return SchedulePlan("windows-task-scheduler", self.task_name, (), (create,))

    def install(self, command: Sequence[str], *, dry_run: bool = False) -> SchedulePlan:
        plan = self.plan(command)
        if not dry_run:
            self._require(self.runner(plan.commands[0]))
        return plan

    def verify(self) -> bool:
        return self.runner(("schtasks", "/Query", "/TN", self.task_name)).returncode == 0

    def uninstall(self, *, dry_run: bool = False) -> None:
        if not dry_run and self.verify():
            self._require(self.runner(("schtasks", "/Delete", "/TN", self.task_name, "/F")))

    @staticmethod
    def _require(result: CommandResult) -> None:
        if result.returncode:
            raise SchedulerError(result.stderr or result.stdout or "scheduler command failed")


class MacOSLaunchdScheduler:
    label = "com.memnetai.integration.flush-due"

    def __init__(self, file_manager: AtomicFileManager, home: Path, uid: int, runner: Runner = subprocess_runner):
        self.files = file_manager
        self.home = home
        self.uid = uid
        self.runner = runner
        self.plist_path = home / "Library" / "LaunchAgents" / f"{self.label}.plist"

    def _content(self, command: Sequence[str]) -> str:
        payload = {
            "Label": self.label,
            "ProgramArguments": list(command),
            "RunAtLoad": True,
            "StartInterval": 60,
        }
        return plistlib.dumps(payload, fmt=plistlib.FMT_XML).decode("utf-8")

    def plan(self, command: Sequence[str]) -> SchedulePlan:
        bootstrap = ("launchctl", "bootstrap", f"gui/{self.uid}", str(self.plist_path))
        return SchedulePlan("launchd", self.label, (self.plist_path,), (bootstrap,))

    def install(self, command: Sequence[str], *, dry_run: bool = False) -> SchedulePlan:
        plan = self.plan(command)
        self.files.write_text(self.plist_path, self._content(command), dry_run=dry_run)
        if not dry_run:
            try:
                current = self.runner(("launchctl", "print", f"gui/{self.uid}/{self.label}"))
                if current.returncode == 0:
                    self.runner(("launchctl", "bootout", f"gui/{self.uid}/{self.label}"))
                WindowsTaskScheduler._require(self.runner(plan.commands[0]))
            except BaseException:
                self.files.restore_all()
                raise
        return plan

    def verify(self) -> bool:
        return self.plist_path.exists() and self.runner(
            ("launchctl", "print", f"gui/{self.uid}/{self.label}")
        ).returncode == 0

    def uninstall(self, *, dry_run: bool = False) -> None:
        if not dry_run and self.verify():
            WindowsTaskScheduler._require(
                self.runner(("launchctl", "bootout", f"gui/{self.uid}/{self.label}"))
            )
        self.files.restore_all(dry_run=dry_run)


class CronScheduler:
    marker = "MEMNETAI-INTEGRATION-FLUSH-DUE"

    def __init__(self, runner: Runner = subprocess_runner):
        self.runner = runner

    def _line(self, command: Sequence[str]) -> str:
        return f"* * * * * {shlex.join(command)} # {self.marker}"

    def plan(self, command: Sequence[str]) -> SchedulePlan:
        return SchedulePlan("cron", self.marker, (), (("crontab", "-"),))

    def _current(self) -> str:
        result = self.runner(("crontab", "-l"))
        return result.stdout if result.returncode == 0 else ""

    def install(self, command: Sequence[str], *, dry_run: bool = False) -> SchedulePlan:
        plan = self.plan(command)
        if not dry_run:
            retained = [line for line in self._current().splitlines() if self.marker not in line]
            payload = "\n".join([*retained, self._line(command)]) + "\n"
            WindowsTaskScheduler._require(self.runner(("crontab", "-"), payload))
        return plan

    def verify(self) -> bool:
        return any(self.marker in line for line in self._current().splitlines())

    def uninstall(self, *, dry_run: bool = False) -> None:
        if dry_run:
            return
        retained = [line for line in self._current().splitlines() if self.marker not in line]
        payload = ("\n".join(retained) + "\n") if retained else ""
        WindowsTaskScheduler._require(self.runner(("crontab", "-"), payload))


class LinuxScheduler:
    service_name = "memnetai-integration-flush-due.service"
    timer_name = "memnetai-integration-flush-due.timer"

    def __init__(
        self,
        file_manager: AtomicFileManager,
        config_home: Path,
        runner: Runner = subprocess_runner,
        cron_factory: Callable[[], CronScheduler] | None = None,
    ) -> None:
        self.files = file_manager
        self.config_home = config_home
        self.runner = runner
        self.cron_factory = cron_factory or (lambda: CronScheduler(runner))
        self.unit_dir = config_home / "systemd" / "user"
        self.service_path = self.unit_dir / self.service_name
        self.timer_path = self.unit_dir / self.timer_name
        self._active: object | None = None

    def _systemd_available(self) -> bool:
        return self.runner(("systemctl", "--user", "show-environment")).returncode == 0

    def _service(self, command: Sequence[str]) -> str:
        escaped = " ".join(shlex.quote(part) for part in command)
        return f"[Unit]\nDescription=Flush due MemNetAI sessions\n\n[Service]\nType=oneshot\nExecStart={escaped}\n"

    @staticmethod
    def _timer() -> str:
        return "[Unit]\nDescription=Check due MemNetAI sessions every minute\n\n[Timer]\nOnBootSec=1min\nOnUnitActiveSec=1min\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n"

    def plan(self, command: Sequence[str], *, systemd: bool | None = None) -> SchedulePlan:
        use_systemd = self._systemd_available() if systemd is None else systemd
        if not use_systemd:
            return self.cron_factory().plan(command)
        commands = (
            ("systemctl", "--user", "daemon-reload"),
            ("systemctl", "--user", "enable", "--now", self.timer_name),
        )
        return SchedulePlan("systemd-user", self.timer_name, (self.service_path, self.timer_path), commands)

    def install(self, command: Sequence[str], *, dry_run: bool = False) -> SchedulePlan:
        plan = self.plan(command)
        if plan.scheduler == "cron":
            cron = self.cron_factory()
            self._active = cron
            if not dry_run:
                self.files.manifest.scheduler = "cron"
                self.files.manifest.scheduler_id = CronScheduler.marker
            return cron.install(command, dry_run=dry_run)
        self._active = "systemd"
        self.files.write_text(self.service_path, self._service(command), dry_run=dry_run)
        self.files.write_text(self.timer_path, self._timer(), dry_run=dry_run)
        if not dry_run:
            self.files.manifest.scheduler = "systemd-user"
            self.files.manifest.scheduler_id = self.timer_name
            try:
                for call in plan.commands:
                    WindowsTaskScheduler._require(self.runner(call))
            except BaseException:
                self.files.restore_all()
                raise
        return plan

    def verify(self) -> bool:
        if isinstance(self._active, CronScheduler) or self.files.manifest.scheduler == "cron":
            cron = self._active if isinstance(self._active, CronScheduler) else self.cron_factory()
            return cron.verify()
        return self.service_path.exists() and self.timer_path.exists() and self.runner(
            ("systemctl", "--user", "is-active", self.timer_name)
        ).returncode == 0

    def uninstall(self, *, dry_run: bool = False) -> None:
        if isinstance(self._active, CronScheduler) or self.files.manifest.scheduler == "cron":
            cron = self._active if isinstance(self._active, CronScheduler) else self.cron_factory()
            cron.uninstall(dry_run=dry_run)
            return
        if not dry_run:
            result = self.runner(("systemctl", "--user", "disable", "--now", self.timer_name))
            if result.returncode not in (0, 1):
                WindowsTaskScheduler._require(result)
        self.files.restore_all(dry_run=dry_run)
        if not dry_run:
            WindowsTaskScheduler._require(self.runner(("systemctl", "--user", "daemon-reload")))
