from __future__ import annotations

import json
from pathlib import Path

from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec
from dix.modules import first_party_module_path

REPOSITORY = Path(__file__).resolve().parents[1]


def main() -> int:
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    sources = (
        ("dix/state", first_party_module_path("dix/state")),
        ("acme/state_demo", REPOSITORY / "examples" / "modules" / "acme" / "state_demo"),
    )
    for module_id, source in sources:
        modules.load_module(source, module_id=module_id)
    instance = applications.create_instance(
        ApplicationInstanceSpec("demo", "acme/state_demo/state", {}, REPOSITORY),
        owner_scope_id="state-pressure",
    )
    try:
        result = instance.api.require("pressure")()
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        applications.destroy_instance("state-pressure", "demo")
        for module_id, _ in reversed(sources):
            modules.unload_module(module_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
