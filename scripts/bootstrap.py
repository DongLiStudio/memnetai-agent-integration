#!/usr/bin/env python3
"""Create/update the isolated runtime and hand off to memnetai-integration."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import venv
from pathlib import Path


def integration_home() -> Path:
    override = os.environ.get("MEMNETAI_INTEGRATION_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "MemNetAI"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MemNetAI"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "memnetai"


def venv_python(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def cli_path(directory: Path) -> Path:
    return directory / ("Scripts/memnetai-integration.exe" if sys.platform == "win32"
                        else "bin/memnetai-integration")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Bootstrap MemNetAI Agent Integration")
    result.add_argument("--api-key-stdin", action="store_true")
    result.add_argument("--dry-run", action="store_true")
    return result


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if sys.version_info < (3, 11):
        emit({"status": "error", "message": "Python 3.11 or newer is required"})
        return 12
    root = Path(__file__).resolve().parents[1]
    environment = integration_home() / "venv"
    executable = cli_path(environment)
    plan = {
        "source": str(root),
        "venv": str(environment),
        "executable": str(executable),
        "credential_input": "stdin" if args.api_key_stdin else None,
    }
    if args.dry_run:
        emit({"status": "dry_run", **plan})
        return 0
    try:
        python = venv_python(environment)
        if not python.exists():
            environment.parent.mkdir(parents=True, exist_ok=True)
            venv.EnvBuilder(with_pip=True).create(environment)
        installed = subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade",
             str(root)],
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
        )
        if installed.returncode != 0:
            emit({"status": "error", "stage": "pip_install",
                  "message": installed.stderr[-2000:]})
            return 12
        command = [str(executable), "install"]
        secret_input = None
        if args.api_key_stdin:
            command.append("--api-key-stdin")
            secret_input = sys.stdin.readline()
        result = subprocess.run(
            command, input=secret_input, text=True, capture_output=True, timeout=240, check=False
        )
        if result.stdout:
            print(result.stdout.rstrip())
        if result.returncode != 0:
            emit({"status": "error", "stage": "integration_install",
                  "message": result.stderr[-2000:], "exit_code": result.returncode})
        return result.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        emit({"status": "error", "stage": "bootstrap", "message": str(exc)})
        return 12


if __name__ == "__main__":
    raise SystemExit(main())
