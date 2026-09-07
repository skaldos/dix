from __future__ import annotations

import sys
from pathlib import Path

from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        print("Usage: run_strand_cli.py APPLICATION_ID [COMMAND OPTIONS...]", file=sys.stderr)
        return 2

    repository = Path(__file__).resolve().parents[3]
    example_modules = repository / "examples" / "modules"
    dix_modules = repository / "unstable" / "modules"
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    loaded: list[str] = []
    created = False
    try:
        for module_id, module_path in (
            ("dix/core/knot", dix_modules / "dix" / "core" / "knot"),
            ("dix/core/app", dix_modules / "dix" / "core" / "app"),
            ("dix/core/cli", dix_modules / "dix" / "core" / "cli"),
            ("dix/core/strand_cli", dix_modules / "dix" / "core" / "strand_cli"),
            ("acme/cli_demo", example_modules / "acme" / "cli_demo"),
        ):
            modules.load_module(module_path, module_id=module_id)
            loaded.append(module_id)
        instance = applications.create_instance(
            ApplicationInstanceSpec(
                id="strand-cli",
                use="dix/core/strand_cli/auto",
                config={},
                config_base_dir=repository,
            ),
            owner_scope_id="example:strand-cli",
        )
        created = True
        return int(instance.api.require("run")(arguments[0], {}, arguments[1:]))
    finally:
        if created:
            applications.destroy_instance("example:strand-cli", "strand-cli")
        for module_id in reversed(loaded):
            modules.unload_module(module_id)


if __name__ == "__main__":
    raise SystemExit(main())
