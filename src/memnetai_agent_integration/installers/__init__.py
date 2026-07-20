"""Cross-platform scheduled-flush installation infrastructure."""

from .files import AtomicFileManager
from .manifest import InstallManifest, ManifestEntry
from .scheduler import (
    CommandResult,
    CronScheduler,
    LinuxScheduler,
    MacOSLaunchdScheduler,
    SchedulePlan,
    WindowsTaskScheduler,
    subprocess_runner,
)

__all__ = [
    "AtomicFileManager",
    "CommandResult",
    "CronScheduler",
    "InstallManifest",
    "LinuxScheduler",
    "MacOSLaunchdScheduler",
    "ManifestEntry",
    "SchedulePlan",
    "WindowsTaskScheduler",
    "subprocess_runner",
]
