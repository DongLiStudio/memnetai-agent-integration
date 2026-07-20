import tempfile
import unittest
from pathlib import Path

from memnetai_agent_integration.installers import (
    AtomicFileManager,
    CommandResult,
    CronScheduler,
    InstallManifest,
    LinuxScheduler,
    MacOSLaunchdScheduler,
    WindowsTaskScheduler,
)


class FakeRunner:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    def __call__(self, args, input_text=None):
        self.calls.append((tuple(args), input_text))
        return self.responses.pop(0) if self.responses else CommandResult(0)


class InstallerTests(unittest.TestCase):
    command = ("python", "-m", "memnetai_agent_integration", "flush-due")

    def test_atomic_write_manifest_and_restore_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "config"
            target.write_text("original", encoding="utf-8")
            manifest = InstallManifest()
            files = AtomicFileManager(root / "backups", manifest)
            files.write_text(target, "installed")
            self.assertEqual(target.read_text(encoding="utf-8"), "installed")
            self.assertTrue(Path(manifest.entries[0].backup_path).exists())
            files.restore_all()
            self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_manifest_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            manifest = InstallManifest(scheduler="cron", scheduler_id="marker")
            manifest.save(path)
            self.assertEqual(InstallManifest.load(path).scheduler, "cron")

    def test_windows_dry_run_and_lifecycle(self):
        runner = FakeRunner()
        scheduler = WindowsTaskScheduler(runner)
        plan = scheduler.install(self.command, dry_run=True)
        self.assertEqual(plan.scheduler, "windows-task-scheduler")
        self.assertEqual(runner.calls, [])
        scheduler.install(self.command)
        self.assertIn("/MO", runner.calls[0][0])
        self.assertIn("1", runner.calls[0][0])
        self.assertTrue(scheduler.verify())
        scheduler.uninstall()
        self.assertEqual(runner.calls[-1][0][1], "/Delete")

    def test_launchd_install_verify_uninstall(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = InstallManifest()
            files = AtomicFileManager(root / "backups", manifest)
            runner = FakeRunner([CommandResult(1), CommandResult(0), CommandResult(0), CommandResult(0)])
            scheduler = MacOSLaunchdScheduler(files, root, 501, runner)
            scheduler.install(self.command)
            content = scheduler.plist_path.read_text(encoding="utf-8")
            self.assertIn("<integer>60</integer>", content)
            self.assertTrue(scheduler.verify())
            scheduler.uninstall()
            self.assertFalse(scheduler.plist_path.exists())

    def test_cron_replaces_only_owned_line_idempotently(self):
        existing = "0 2 * * * backup\n* * * * * old # MEMNETAI-INTEGRATION-FLUSH-DUE\n"
        runner = FakeRunner([CommandResult(0, existing), CommandResult(0), CommandResult(0, existing)])
        scheduler = CronScheduler(runner)
        scheduler.install(self.command)
        payload = runner.calls[1][1]
        self.assertIn("backup", payload)
        self.assertEqual(payload.count(scheduler.marker), 1)
        self.assertTrue(scheduler.verify())

    def test_linux_systemd_and_cron_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = AtomicFileManager(root / "backups", InstallManifest())
            systemd_runner = FakeRunner()
            systemd = LinuxScheduler(files, root, systemd_runner)
            plan = systemd.install(self.command)
            self.assertEqual(plan.scheduler, "systemd-user")
            self.assertIn("OnUnitActiveSec=1min", systemd.timer_path.read_text(encoding="utf-8"))

            cron_runner = FakeRunner([CommandResult(1), CommandResult(1), CommandResult(0)])
            fallback = LinuxScheduler(
                AtomicFileManager(root / "other", InstallManifest()), root / "other-config", cron_runner
            )
            plan = fallback.install(self.command)
            self.assertEqual(plan.scheduler, "cron")
            self.assertEqual(cron_runner.calls[-1][0], ("crontab", "-"))

    def test_all_dry_runs_have_no_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = FakeRunner()
            files = AtomicFileManager(root / "backups", InstallManifest())
            MacOSLaunchdScheduler(files, root, 501, runner).install(self.command, dry_run=True)
            LinuxScheduler(files, root, runner).install(self.command, dry_run=True)
            self.assertFalse((root / "Library").exists())
            # Linux planning performs one read-only capability probe only.
            self.assertEqual(runner.calls, [(('systemctl', '--user', 'show-environment'), None)])

    def test_launchd_command_failure_rolls_back_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = AtomicFileManager(root / "backups", InstallManifest())
            runner = FakeRunner([CommandResult(1), CommandResult(2, stderr="denied")])
            scheduler = MacOSLaunchdScheduler(files, root, 501, runner)
            with self.assertRaises(RuntimeError):
                scheduler.install(self.command)
            self.assertFalse(scheduler.plist_path.exists())

    def test_linux_command_failure_rolls_back_units(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = AtomicFileManager(root / "backups", InstallManifest())
            runner = FakeRunner([CommandResult(0), CommandResult(3, stderr="failed")])
            scheduler = LinuxScheduler(files, root, runner)
            with self.assertRaises(RuntimeError):
                scheduler.install(self.command)
            self.assertFalse(scheduler.service_path.exists())
            self.assertFalse(scheduler.timer_path.exists())


if __name__ == "__main__":
    unittest.main()
