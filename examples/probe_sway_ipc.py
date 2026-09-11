from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dix.core import CompositionComponent, ModuleComponent, create_core_component_registry
from dix.core.composition import CompositionInstanceSpec
from dix.modules import first_party_module_path


def main() -> int:
    socket = os.environ.get("SWAYSOCK", "")
    if not socket:
        print("live_sway=not_run")
        return 0
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    compositions = registry.require("composition", CompositionComponent)
    modules.load_module(first_party_module_path("dix/sway"), module_id="dix/sway")
    instance = compositions.create_instance(
        CompositionInstanceSpec("ipc", "dix/sway/ipc", {}, Path.cwd()),
        owner_scope_id="probe",
    )
    result = {"focused_con_id": instance.api.require("focused_con_id")()}
    print(json.dumps(result, sort_keys=True))
    print("live_sway=passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"live_sway=failed error={exc}", file=sys.stderr)
        raise
