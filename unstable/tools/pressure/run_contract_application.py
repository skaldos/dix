from __future__ import annotations

import asyncio
import json
from pathlib import Path

from dix.core import (
    ApplicationComponent,
    ModuleComponent,
    ModuleComponentError,
    create_core_component_registry,
)
from dix.core.application import ApplicationInstanceSpec
from dix.core.function import FunctionInputError


def main() -> int:
    repository = Path(__file__).resolve().parents[3]
    module_root = (
        repository / "tests" / "fixtures" / "modules" / "acme" / "contract_app"
    )
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)

    inspection = modules.inspect_module(module_root, module_id="acme/contract_app")
    loaded = modules.load_module(module_root, module_id="acme/contract_app")
    instance = applications.create_instance(
        ApplicationInstanceSpec(
            id="pressure",
            use="acme/contract_app/echo",
            config={},
            config_base_dir=module_root,
        ),
        owner_scope_id="pressure",
    )
    result = asyncio.run(instance.api.invoke("echo", "dix"))

    invalid_input = None
    try:
        asyncio.run(instance.api.invoke("echo", 42))
    except FunctionInputError as exc:
        invalid_input = str(exc)

    unload_blocker = None
    try:
        modules.unload_module("acme/contract_app")
    except ModuleComponentError as exc:
        unload_blocker = str(exc).splitlines()[0]

    applications.destroy_instance("pressure", "pressure")
    modules.unload_module("acme/contract_app")
    print(
        json.dumps(
            {
                "module": inspection.id,
                "artifact_digest": inspection.artifact_digest,
                "contracts": [item.id for item in inspection.contract_definitions],
                "compositions": sorted(loaded.compositions),
                "applications": sorted(loaded.applications),
                "function_contract": instance.api.describe("echo").binding.contract.id,
                "result": result,
                "invalid_input": invalid_input,
                "unload_blocker": unload_blocker,
                "remaining_modules": [item.inspection.id for item in modules.modules()],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
