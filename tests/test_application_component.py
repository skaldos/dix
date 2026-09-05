from __future__ import annotations

from pathlib import Path

import pytest

from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationComponentError
from dix.core.module.component import ModuleComponentError


def write_application(module: Path, runtime: str) -> Path:
    root = module / "apps" / "demo"
    root.mkdir(parents=True)
    (root / "app.toml").write_text('[app]\nid = "demo"\n')
    (root / "runtime.py").write_text(runtime)
    return root


def test_application_component_is_runtime_scoped_and_lists_loaded_definitions(
    tmp_path: Path,
) -> None:
    module = tmp_path / "module"
    write_application(
        module,
        "class Runtime:\n    def __init__(self, *, context, config): pass\n",
    )
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    first = registry.create_scope("first").require("application", ApplicationComponent)
    second = registry.create_scope("second").require("application", ApplicationComponent)

    modules.load_module(module, module_id="acme/demo")

    assert first is second
    assert [item.id for item in first.definitions()] == ["acme/demo/demo"]
    assert first.describe_application("acme/demo/demo").functions == ()


def test_invalid_constructor_is_rejected_before_definition_publication(
    tmp_path: Path,
) -> None:
    module = tmp_path / "module"
    write_application(
        module,
        "class Runtime:\n    def __init__(self, *, context, config, extra): pass\n",
    )
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)

    with pytest.raises(ModuleComponentError, match="keyword-only parameters"):
        modules.load_module(module, module_id="acme/demo")

    assert applications.definitions() == ()


def test_unknown_application_instance_lookup_is_deterministic() -> None:
    registry = create_core_component_registry()
    applications = registry.require("application", ApplicationComponent)

    with pytest.raises(ApplicationComponentError, match="instance not found"):
        applications.require_instance("owner", "missing")
