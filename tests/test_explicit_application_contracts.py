from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from dix.core import (
    ApplicationComponent,
    CompositionComponent,
    ModuleComponent,
    ModuleComponentError,
    create_core_component_registry,
)
from dix.core.application import ApplicationInstanceSpec

FIXTURE = Path(__file__).parent / "fixtures" / "modules" / "acme" / "contract_app"


def components() -> tuple[ModuleComponent, CompositionComponent, ApplicationComponent]:
    registry = create_core_component_registry()
    return (
        registry.require("module", ModuleComponent),
        registry.require("composition", CompositionComponent),
        registry.require("application", ApplicationComponent),
    )


def test_contract_composition_application_invocation() -> None:
    modules, compositions, applications = components()
    loaded = modules.load_module(FIXTURE, module_id="acme/contract_app")

    assert tuple(item.id for item in loaded.contracts.values()) == (
        "acme/contract_app/echo",
    )
    composition = compositions.describe_function("acme/contract_app/echo", "echo")
    application = applications.describe_function("acme/contract_app/echo", "echo")
    assert composition.binding.contract.reference == application.binding.contract.reference

    instance = applications.create_instance(
        ApplicationInstanceSpec(
            id="echo",
            use="acme/contract_app/echo",
            config={},
            config_base_dir=FIXTURE,
        ),
        owner_scope_id="test",
    )
    assert asyncio.run(instance.api.invoke("echo", "hello")) == "hello"
    assert instance.runtime.internal() == "not exposed"
    with pytest.raises(Exception, match="input is incompatible"):
        asyncio.run(instance.api.invoke("echo", 42))


def test_missing_contract_reference_fails_before_publication(tmp_path: Path) -> None:
    module = tmp_path / "broken"
    root = module / "compositions" / "echo"
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(
        '[composition]\nid = "echo"\n[functions.echo]\ndescription = "broken"\n'
    )
    (root / "runtime.py").write_text(
        "class Runtime:\n"
        "    def __init__(self, *, context, config): pass\n"
        "    def echo(self, value): return value\n"
    )
    modules, compositions, _ = components()

    with pytest.raises(Exception, match="functions.echo.contract must be a TOML table"):
        modules.load_module(module, module_id="acme/broken")
    assert modules.modules() == ()
    assert compositions.definitions() == ()


def test_unknown_contract_version_rolls_back_whole_module(tmp_path: Path) -> None:
    module = tmp_path / "wrong-version"
    root = module / "contracts" / "echo"
    root.mkdir(parents=True)
    (root / "contract.toml").write_text(
        '[contract]\nid = "echo"\nversion = "1"\n'
        '[input]\ntype = "string"\n[output]\ntype = "string"\n'
    )
    composition = module / "compositions" / "echo"
    composition.mkdir(parents=True)
    (composition / "composition.toml").write_text(
        '[composition]\nid = "echo"\n[functions.echo]\n'
        '[functions.echo.contract]\nuse = "acme/wrong/echo"\nversion = "2"\n'
    )
    (composition / "runtime.py").write_text(
        "class Runtime:\n"
        "    def __init__(self, *, context, config): pass\n"
        "    def echo(self, value): return value\n"
    )
    modules, compositions, _ = components()

    with pytest.raises(ModuleComponentError, match="contract is not loaded"):
        modules.load_module(module, module_id="acme/wrong")
    assert modules.modules() == ()
    assert modules.contracts() == ()
    assert compositions.definitions() == ()


def test_contract_module_cannot_unload_while_foreign_function_uses_it(
    tmp_path: Path,
) -> None:
    contract_module = tmp_path / "contract"
    contract = contract_module / "contracts" / "echo"
    contract.mkdir(parents=True)
    (contract / "contract.toml").write_text(
        '[contract]\nid = "echo"\nversion = "1"\n'
        '[input]\ntype = "string"\n[output]\ntype = "string"\n'
    )
    consumer_module = tmp_path / "consumer"
    composition = consumer_module / "compositions" / "echo"
    composition.mkdir(parents=True)
    (composition / "composition.toml").write_text(
        '[composition]\nid = "echo"\n[functions.echo]\n'
        '[functions.echo.contract]\nuse = "acme/contracts/echo"\nversion = "1"\n'
    )
    (composition / "runtime.py").write_text(
        "class Runtime:\n"
        "    def __init__(self, *, context, config): pass\n"
        "    def echo(self, value): return value\n"
    )
    modules, _, _ = components()
    modules.load_module(contract_module, module_id="acme/contracts")
    modules.load_module(consumer_module, module_id="acme/consumer")

    with pytest.raises(ModuleComponentError, match="requires contract"):
        modules.unload_module("acme/contracts")
    modules.unload_module("acme/consumer")
    modules.unload_module("acme/contracts")
    assert modules.modules() == ()
