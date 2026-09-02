from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import load_effective_config, write_default_config


def _json_print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def cmd_config(args: argparse.Namespace) -> int:
    path = Path(args.path) if getattr(args, "path", None) else Path.cwd() / "dix.toml"
    if args.config_cmd == "init":
        created = write_default_config(path)
        print(f"created: {str(path)}" if created else f"exists: {str(path)}")
        return 0

    cfg = load_effective_config()
    if args.config_cmd == "validate":
        print("config valid")
        return 0
    if args.config_cmd == "effective":
        _json_print(
            {
                "values": cfg.values,
                "sources": {
                    key: {"source": src.source, "detail": src.detail, "value": src.value}
                    for key, src in cfg.sources.items()
                },
                "loaded_files": [str(p) for p in cfg.loaded_files],
            }
        )
        return 0
    if args.config_cmd == "explain":
        src = cfg.explain(args.key)
        _json_print({"key": src.key, "value": src.value, "source": src.source, "detail": src.detail})
        return 0
    if args.config_cmd == "edit":
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
        if not editor:
            raise SystemExit("VISUAL or EDITOR must be set")
        if not path.exists():
            write_default_config(path)
        return subprocess.call([editor, str(path)])
    raise SystemExit(f"unknown config command: {args.config_cmd}")


def _interface_dirs() -> list[Path]:
    cfg = load_effective_config()
    return [Path(item) for item in cfg.values["interface_dirs"]]


def _interface_path(interface_id: str) -> Path:
    base = _interface_dirs()[0]
    return base / f"{interface_id}.toml"


def _read_interface_title(path: Path) -> str:
    from .registry import load_interface

    return load_interface(path).interface.title


def cmd_interface(args: argparse.Namespace) -> int:
    if args.interface_cmd == "list":
        rows = []
        for directory in _interface_dirs():
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.toml")):
                rows.append({"id": path.stem, "title": _read_interface_title(path), "path": str(path)})
        _json_print(rows)
        return 0

    path = _interface_path(args.id)
    if args.interface_cmd == "new":
        if path.exists():
            raise SystemExit(f"interface already exists: {args.id}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"[interface]\n"
            f"id = \"{args.id}\"\n"
            f"title = \"{args.id.replace('_', ' ').title()}\"\n"
            f"access = {{ mode = \"public\" }}\n\n"
            f"[[components]]\n"
            f"id = \"title\"\n"
            f"use = \"input\"\n"
            f"config = {{ label = \"Title\", placeholder = \"Enter a title\" }}\n\n"
            f"[[components]]\n"
            f"id = \"kind\"\n"
            f"use = \"select\"\n"
            f"config = {{ label = \"Kind\", mode = \"single\", options = [{{ id = \"demo\", label = \"Demo\" }}] }}\n"
        )
        print(f"created: {path}")
        return 0
    if args.interface_cmd == "delete":
        if not path.exists():
            raise SystemExit(f"interface not found: {args.id}")
        if not args.force:
            raise SystemExit("refusing to delete without --force")
        path.unlink()
        print(f"deleted: {path}")
        return 0
    if args.interface_cmd == "edit":
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
        if not editor:
            raise SystemExit("VISUAL or EDITOR must be set")
        if not path.exists():
            raise SystemExit(f"interface not found: {args.id}")
        return subprocess.call([editor, str(path)])
    raise SystemExit(f"unknown interface command: {args.interface_cmd}")


def cmd_component(args: argparse.Namespace) -> int:
    if args.component_cmd == "list":
        from .registry import component_definitions

        _json_print([definition.model_dump() for definition in component_definitions()])
        return 0
    raise SystemExit(f"unknown component command: {args.component_cmd}")


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    return serve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dix", description="Declarative Interface eXecutor")
    sub = parser.add_subparsers(dest="cmd", required=True)

    config = sub.add_parser("config")
    config_sub = config.add_subparsers(dest="config_cmd", required=True)
    config_init = config_sub.add_parser("init")
    config_init.add_argument("--path", default=None)
    config_sub.add_parser("validate")
    config_sub.add_parser("effective")
    config_explain = config_sub.add_parser("explain")
    config_explain.add_argument("key")
    config_edit = config_sub.add_parser("edit")
    config_edit.add_argument("--path", default=None)
    config.set_defaults(func=cmd_config)

    interface = sub.add_parser("interface")
    interface_sub = interface.add_subparsers(dest="interface_cmd", required=True)
    interface_sub.add_parser("list")
    interface_new = interface_sub.add_parser("new")
    interface_new.add_argument("id")
    interface_edit = interface_sub.add_parser("edit")
    interface_edit.add_argument("id")
    interface_delete = interface_sub.add_parser("delete")
    interface_delete.add_argument("id")
    interface_delete.add_argument("--force", action="store_true")
    interface.set_defaults(func=cmd_interface)

    component = sub.add_parser("component")
    component_sub = component.add_subparsers(dest="component_cmd", required=True)
    component_sub.add_parser("list")
    component.set_defaults(func=cmd_component)

    serve = sub.add_parser("serve")
    serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyError as e:
        print(f"unknown key: {e.args[0]}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
