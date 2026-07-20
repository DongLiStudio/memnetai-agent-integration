import argparse
import json
from pathlib import Path

from . import __version__
from .config import IntegrationDefaults
from .database import initialize


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memnetai-integration")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Show scaffold configuration")
    doctor.add_argument("--json", action="store_true")

    init_db = subparsers.add_parser("init-db", help="Initialize a local SQLite database")
    init_db.add_argument("path", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    defaults = IntegrationDefaults()

    if args.command == "doctor":
        result = {
            "status": "scaffold",
            "version": __version__,
            "memory_agent_name": defaults.memory_agent_name,
            "namespace": defaults.namespace,
            "idle_timeout_minutes": defaults.idle_timeout_minutes,
            "max_messages": defaults.max_messages,
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            for key, value in result.items():
                print(f"{key}: {value}")
        return 0

    if args.command == "init-db":
        initialize(args.path)
        print(f"initialized: {args.path}")
        return 0

    return 2

