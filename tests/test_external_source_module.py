from __future__ import annotations

from pathlib import Path

from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec

FIXTURE = Path(__file__).parent / "fixtures" / "external_module"


def test_explicit_external_source_module_lifecycle() -> None:
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)

    loaded = modules.load_module(FIXTURE, module_id="external/demo")
    assert tuple(loaded.compositions) == ("external/demo/prefix",)
    assert tuple(loaded.applications) == ("external/demo/consumer",)

    instance = applications.create_instance(
        ApplicationInstanceSpec(
            id="consumer",
            use="external/demo/consumer",
            config={},
            config_base_dir=FIXTURE,
        ),
        owner_scope_id="external-test",
    )
    assert instance.api.require("run")("value") == "consumer[external<value>]"

    applications.destroy_instance("external-test", "consumer")
    assert modules.unload_module("external/demo") is loaded
    assert modules.modules() == ()
