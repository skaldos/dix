from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys

from dix.modules import first_party_module_path


FORBIDDEN_MODULES = ("roba", "httpx", "pydantic", "typer")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"left", "right", "up", "down"}:
        print("usage: dix_sway_navigation.py {left|right|up|down}", file=sys.stderr)
        return 2
    projection = os.environ.get("DIX_SWAY_ACTIVE_MEMBERS_FILE")
    if not projection:
        print("DIX_SWAY_ACTIVE_MEMBERS_FILE must be set", file=sys.stderr)
        return 2
    try:
        module_root = first_party_module_path("dix/sway")
        assembly = _load_assembly(module_root / "navigation_entry.py")
        result = assembly.run(module_root, Path(projection), sys.argv[1])
        loaded = sorted(name for name in FORBIDDEN_MODULES if name in sys.modules)
        if loaded:
            raise RuntimeError(f"forbidden hot-path modules loaded: {', '.join(loaded)}")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


def _load_assembly(path: Path):
    spec = importlib.util.spec_from_file_location("dix_sway_navigation_entry", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Sway navigation assembly: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    raise SystemExit(main())
