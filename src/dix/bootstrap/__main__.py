from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .build import LauncherBuildError, build_launcher
from .spec import LauncherSpecError


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m dix.bootstrap",
        description="Build explicit DIX application launchers.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Build one Python launcher.")
    build.add_argument("spec", type=Path, help="Path to the launcher TOML specification.")
    build.add_argument("--output", type=Path, required=True, help="Generated Python file.")
    build.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing output file atomically.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "build":
        try:
            output = build_launcher(
                arguments.spec,
                arguments.output,
                replace=arguments.replace,
            )
        except (LauncherSpecError, LauncherBuildError) as exc:
            parser.exit(2, f"dix bootstrap: {exc}\n")
        print(output)
        return 0
    parser.error(f"unknown command: {arguments.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
