from __future__ import annotations

import sys
from pathlib import Path

from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec


def main(argv: list[str] | None = None) -> int:
    repository = Path(__file__).resolve().parents[1]
    modules_root = repository / "examples" / "modules"
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(modules_root / "dix" / "core" / "app", module_id="dix/core/app")
    modules.load_module(modules_root / "dix" / "core" / "cli", module_id="dix/core/cli")
    modules.load_module(modules_root / "acme" / "cli_demo", module_id="acme/cli_demo")
    instance = applications.create_instance(
        ApplicationInstanceSpec(
            id="cli",
            use="acme/cli_demo/cli",
            config={},
            config_base_dir=repository,
        ),
        owner_scope_id="example:cli",
    )
    try:
        return int(instance.api.require("run")(list(sys.argv[1:] if argv is None else argv)))
    finally:
        applications.destroy_instance("example:cli", "cli")
        modules.unload_module("acme/cli_demo")
        modules.unload_module("dix/core/cli")
        modules.unload_module("dix/core/app")


if __name__ == "__main__":
    raise SystemExit(main())
