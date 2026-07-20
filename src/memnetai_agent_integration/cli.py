from __future__ import annotations

import argparse
import getpass
import hmac
import json
import os
import shutil
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .adapters import CodexAdapter, HermesAdapter, WorkBuddyAdapter
from .client import SDKClient
from .config import (
    DASHBOARD_URL, IntegrationDefaults, default_config_path, load_config, public_config,
    save_config,
)
from .database import due_sessions, initialize, retryable_batches, submitted_batches
from .hooks import normalize, read_payload
from .installers import (
    AtomicFileManager, InstallManifest, LinuxScheduler, MacOSLaunchdScheduler,
    WindowsTaskScheduler,
)
from .runtime import MemoryRuntime
from .secrets import SecretError, delete_api_key, load_api_key, save_api_key, secret_path


def _home() -> Path:
    override = os.environ.get("MEMNETAI_INTEGRATION_HOME")
    if override:
        return Path(override).expanduser()
    return IntegrationDefaults().database_path.parent


def _executable() -> Path:
    override = os.environ.get("MEMNETAI_INTEGRATION_EXECUTABLE")
    return Path(override or shutil.which("memnetai-integration") or sys.argv[0]).resolve()


def _adapters() -> list[Any]:
    return [CodexAdapter(), WorkBuddyAdapter(), HermesAdapter()]


def _scheduler(home: Path, manifest: InstallManifest | None = None) -> Any:
    manifest = manifest or InstallManifest()
    files = AtomicFileManager(home / "backups", manifest)
    if sys.platform == "win32":
        return WindowsTaskScheduler()
    if sys.platform == "darwin":
        return MacOSLaunchdScheduler(files, Path.home(), os.getuid())
    return LinuxScheduler(files, Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memnetai-integration")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    install = sub.add_parser("install")
    source = install.add_mutually_exclusive_group()
    source.add_argument("--api-key-stdin", action="store_true")
    source.add_argument("--interactive", action="store_true")
    install.add_argument("--dry-run", action="store_true")
    sub.add_parser("doctor").add_argument("--json", action="store_true")
    repair = sub.add_parser("repair")
    repair.add_argument("--dry-run", action="store_true")
    uninstall = sub.add_parser("uninstall")
    uninstall.add_argument("--purge-data", action="store_true")
    uninstall.add_argument("--dry-run", action="store_true")
    sub.add_parser("hook-before")
    sub.add_parser("hook-after")
    sub.add_parser("flush-due")
    flush = sub.add_parser("flush-session")
    flush.add_argument("--session-id")
    init_db = sub.add_parser("init-db")
    init_db.add_argument("path", type=Path)
    return parser


def _emit(value: Any) -> None:
    def encode(item: Any) -> Any:
        return asdict(item) if is_dataclass(item) else str(item)

    print(json.dumps(value, ensure_ascii=False, default=encode))


def _runtime() -> MemoryRuntime:
    config = load_config()
    return MemoryRuntime(config, SDKClient(load_api_key(_home()), config.base_url))


def _install(args: argparse.Namespace, *, repair: bool = False) -> int:
    home = _home()
    existing = secret_path(home).exists()
    key: str | None = None
    if getattr(args, "api_key_stdin", False):
        key = sys.stdin.readline().strip()
    elif getattr(args, "interactive", False):
        key = getpass.getpass("MemNetAI API Key: ").strip()
    elif existing:
        key = load_api_key(home)
    if not key and not args.dry_run:
        _emit({"status": "waiting_for_api_key", "input": "stdin_or_getpass"})
        return 0
    config = load_config()
    executable = _executable()
    detected = [adapter for adapter in _adapters() if adapter.detect()]
    if not detected:
        raise RuntimeError("未检测到已原生深度适配的宿主；请由安装 Skill 执行通用 Agent 能力探测")
    manifest = InstallManifest()
    scheduler = _scheduler(home, manifest)
    if args.dry_run:
        results = [adapter.install(executable, dry_run=True) for adapter in detected]
        plan = scheduler.install((str(executable), "flush-due"), dry_run=True)
        _emit({"status": "dry_run", "hosts": results, "scheduler": plan,
               "requires": ["api_key"] if not key else []})
        return 0
    # Validate before persisting or mutating host configuration.
    SDKClient(key, config.base_url).recall(
        memory_agent_name=config.memory_agent_name, namespace=config.namespace,
        query="MemNetAI integration installation check", timeout=config.recall_timeout_seconds,
    )
    previous_key = load_api_key(home) if existing else None
    config_path = default_config_path()
    previous_config = config_path.read_bytes() if config_path.exists() else None
    database_existed = config.database_path.exists()
    installed: list[Any] = []
    scheduler_installed = False
    try:
        if not args.dry_run:
            save_api_key(home, key)
            save_config(config)
            initialize(config.database_path)
        results = []
        for adapter in detected:
            results.append(adapter.install(executable, dry_run=args.dry_run))
            installed.append(adapter)
        plan = scheduler.install((str(executable), "flush-due"), dry_run=args.dry_run)
        scheduler_installed = not args.dry_run
        if not args.dry_run:
            manifest.scheduler = plan.scheduler
            manifest.scheduler_id = plan.identifier
            manifest.save(home / "install-manifest.json")
    except BaseException:
        if not args.dry_run:
            if scheduler_installed:
                try:
                    scheduler.uninstall()
                except Exception:
                    pass
            for adapter in reversed(installed):
                try:
                    adapter.uninstall(executable)
                except Exception:
                    pass
            if previous_key is None:
                delete_api_key(home)
            else:
                save_api_key(home, previous_key)
            if previous_config is None:
                config_path.unlink(missing_ok=True)
            else:
                config_path.write_bytes(previous_config)
            if not database_existed:
                config.database_path.unlink(missing_ok=True)
                Path(str(config.database_path) + "-wal").unlink(missing_ok=True)
                Path(str(config.database_path) + "-shm").unlink(missing_ok=True)
        raise
    _emit({"status": "repaired" if repair else "installed", "hosts": results,
           "scheduler": plan.scheduler, "dry_run": args.dry_run})
    return 0


def _doctor(as_json: bool) -> int:
    home = _home()
    executable = _executable()
    results = [adapter.verify(executable) for adapter in _adapters()]
    manifest_path = home / "install-manifest.json"
    manifest = InstallManifest.load(manifest_path) if manifest_path.exists() else InstallManifest()
    scheduler_ok = _scheduler(home, manifest).verify() if manifest.scheduler else False
    healthy = secret_path(home).exists() and scheduler_ok and any(r.verified for r in results)
    result = {
        "status": "ok" if healthy else "needs_repair",
        "version": __version__,
        "api_key_configured": secret_path(home).exists(),
        "scheduler": scheduler_ok,
        "hosts": results,
        "config": public_config(load_config()),
    }
    if as_json:
        _emit(result)
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0 if result["status"] == "ok" else 1


def _uninstall(args: argparse.Namespace) -> int:
    home, executable = _home(), _executable()
    results = [adapter.uninstall(executable, dry_run=args.dry_run) for adapter in _adapters()]
    manifest_path = home / "install-manifest.json"
    manifest = InstallManifest.load(manifest_path) if manifest_path.exists() else InstallManifest()
    if manifest.scheduler:
        _scheduler(home, manifest).uninstall(dry_run=args.dry_run)
    if not args.dry_run:
        delete_api_key(home)
        manifest_path.unlink(missing_ok=True)
        if args.purge_data:
            database = load_config().database_path
            database.unlink(missing_ok=True)
            Path(str(database) + "-wal").unlink(missing_ok=True)
            Path(str(database) + "-shm").unlink(missing_ok=True)
            default_config_path().unlink(missing_ok=True)
    _emit({"status": "uninstalled", "hosts": results, "data_preserved": not args.purge_data})
    return 0


def _hook(event: str) -> int:
    try:
        message = normalize(read_payload(sys.stdin), event=event)
        runtime = _runtime()
        if event == "before":
            if not message.prompt:
                _emit({})
                return 0
            try:
                if hmac.compare_digest(message.prompt.strip(), load_api_key(_home())):
                    _emit({})
                    return 0
            except SecretError:
                pass
            result = runtime.before_reply(session_id=message.session_id, host=message.host,
                                          prompt=message.prompt,
                                          message_id=message.event_id("user", message.prompt))
            memories = tuple(getattr(result.payload, "memories", ())) if result.ok else ()
            context = "\n\n".join(memories)
            output: dict[str, Any] = {}
            if result.user_notice:
                notice = (
                    "[MemNetAI 状态] 长期记忆暂不可用。请在本轮明确通知用户："
                    f"{result.user_notice} {DASHBOARD_URL}"
                )
                context = "\n\n".join(item for item in (context, notice) if item)
            if context:
                output = ({"context": context} if message.host == "hermes" else
                          {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                   "additionalContext": context}})
            if result.user_notice:
                output["systemMessage"] = f"{result.user_notice} {DASHBOARD_URL}"
            _emit(output)
            return 0
        if not message.response:
            _emit({"systemMessage": "MemNetAI 未能读取本轮助手回复，已跳过记录。"})
            return 0
        result = runtime.after_reply(session_id=message.session_id, host=message.host,
                                     response=message.response,
                                     message_id=message.event_id("assistant", message.response))
        config = runtime.config
        due = due_sessions(config.database_path, max_messages=config.max_messages)
        if message.session_id in due:
            result = runtime.submit_session(message.session_id, "message_threshold")
        failure = {"systemMessage": f"{result.user_notice} {DASHBOARD_URL}"}
        _emit({} if result.ok else failure)
        return 0
    except Exception as exc:
        _emit({"systemMessage": f"MemNetAI {event} hook 失败：{exc}。请检查控制台：{DASHBOARD_URL}"})
        return 0


def _flush(session_id: str | None = None) -> int:
    runtime = _runtime()
    config = runtime.config
    sessions = (
        [session_id]
        if session_id
        else due_sessions(config.database_path, max_messages=config.max_messages)
    )
    reason = "manual" if session_id else "idle_or_threshold"
    results = {
        f"session:{item}": runtime.submit_session(item, reason)
        for item in sessions if item
    }
    if not session_id:
        for batch in submitted_batches(config.database_path):
            if batch.remote_task_id:
                results[f"poll:{batch.batch_id}"] = runtime.check_submission(
                    batch.batch_id, batch.remote_task_id
                )
        for batch_id in retryable_batches(config.database_path):
            results[f"retry:{batch_id}"] = runtime.retry_submission(batch_id)
    _emit({"status": "complete", "results": results})
    return 0 if all(result.ok for result in results.values()) else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "install":
            return _install(args)
        if args.command == "doctor":
            return _doctor(args.json)
        if args.command == "repair":
            args.api_key_stdin = args.interactive = False
            return _install(args, repair=True)
        if args.command == "uninstall":
            return _uninstall(args)
        if args.command in {"hook-before", "hook-after"}:
            return _hook(args.command.removeprefix("hook-"))
        if args.command == "flush-due":
            return _flush()
        if args.command == "flush-session":
            payload = read_payload(sys.stdin) if not args.session_id else {}
            return _flush(args.session_id or str(payload.get("session_id") or ""))
        if args.command == "init-db":
            initialize(args.path)
            print(f"initialized: {args.path}")
            return 0
    except (SecretError, ValueError, OSError, RuntimeError) as exc:
        _emit({"status": "error", "message": str(exc), "dashboard_url": DASHBOARD_URL})
        return 1
    return 2
