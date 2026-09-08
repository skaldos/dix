from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from dix.core import (
    ApplicationComponent,
    CompositionComponent,
    CompositionComponentError,
    FunctionInputError,
    FunctionOutputError,
    ModuleComponent,
    ModuleComponentError,
    create_core_component_registry,
)
from dix.core.application import ApplicationInstanceSpec
from dix.core.composition import CompositionInstanceSpec


def core_components() -> tuple[ModuleComponent, CompositionComponent, ApplicationComponent]:
    registry = create_core_component_registry()
    return (
        registry.require("module", ModuleComponent),
        registry.require("composition", CompositionComponent),
        registry.require("application", ApplicationComponent),
    )


def write_model_contract(module: Path, *, module_id: str) -> None:
    model = module / "models" / "request" / "model.toml"
    model.parent.mkdir(parents=True)
    model.write_text(
        '[model]\nid = "request"\nversion = "1"\n\n'
        '[fields.name]\ntype = "string"\n\n'
        '[fields.age]\ntype = "integer"\n'
    )
    contract = module / "contracts" / "request" / "contract.toml"
    contract.parent.mkdir(parents=True)
    endpoint = (
        'type = "model"\n'
        f'use = "{module_id}/request"\n'
        'version = "1"\n'
    )
    contract.write_text(
        '[contract]\nid = "request"\nversion = "1"\n\n'
        f'[input]\n{endpoint}\n[output]\n{endpoint}'
    )


def function_spec(module_id: str) -> str:
    return (
        '[functions.echo.contract]\n'
        f'use = "{module_id}/request"\nversion = "1"\n\n'
        '[functions.second.contract]\n'
        f'use = "{module_id}/request"\nversion = "1"\n\n'
        '[functions.invalid_output.contract]\n'
        f'use = "{module_id}/request"\nversion = "1"\n'
    )


def write_model_function_module(module: Path, *, module_id: str) -> Path:
    write_model_contract(module, module_id=module_id)
    composition = module / "compositions" / "processor"
    composition.mkdir(parents=True)
    (composition / "composition.toml").write_text(
        '[composition]\nid = "processor"\n\n' + function_spec(module_id)
    )
    runtime = (
        'class Runtime:\n'
        '    def __init__(self, *, context, config): pass\n'
        '    def echo(self, value): return value\n'
        '    def second(self, value): return {"name": "second", "age": value["age"]}\n'
        '    def invalid_output(self, value): return {"name": value["name"]}\n'
    )
    (composition / "runtime.py").write_text(runtime)
    application = module / "apps" / "processor"
    application.mkdir(parents=True)
    (application / "app.toml").write_text(
        '[app]\nid = "processor"\n\n' + function_spec(module_id)
    )
    (application / "runtime.py").write_text(runtime)
    return module


def test_model_contract_functions_use_norn_for_composition_and_application(
    tmp_path: Path,
) -> None:
    module_id = "acme/model_functions"
    root = write_model_function_module(tmp_path / "module", module_id=module_id)
    modules, compositions, applications = core_components()
    modules.load_module(root, module_id=module_id)

    composition = compositions.create_instance(
        CompositionInstanceSpec("processor", f"{module_id}/processor", {}, root),
        owner_scope_id="composition-test",
    )
    application = applications.create_instance(
        ApplicationInstanceSpec("processor", f"{module_id}/processor", {}, root),
        owner_scope_id="application-test",
    )
    value = {"name": "Ada", "age": 42}

    assert dict(asyncio.run(composition.api.invoke("echo", value))) == value
    assert dict(asyncio.run(composition.api.invoke("second", value))) == {
        "name": "second",
        "age": 42,
    }
    assert dict(asyncio.run(application.api.invoke("echo", value))) == value

    for invalid, code in (
        ({"name": "Ada"}, "missing_field"),
        ({"name": "Ada", "age": 42, "extra": True}, "additional_field"),
        ({"name": "Ada", "age": "42"}, "incompatible_type"),
    ):
        with pytest.raises(FunctionInputError) as captured:
            asyncio.run(composition.api.invoke("echo", invalid))
        assert code in {issue.code for issue in captured.value.issues}

    with pytest.raises(FunctionOutputError) as captured:
        asyncio.run(composition.api.invoke("invalid_output", value))
    assert "missing_field" in {issue.code for issue in captured.value.issues}


def write_custom_contract_module(
    module: Path,
    *,
    module_id: str,
    with_handler: bool,
) -> Path:
    contract = module / "contracts" / "token" / "contract.toml"
    contract.parent.mkdir(parents=True)
    contract.write_text(
        '[contract]\nid = "token"\n\n'
        f'[input]\ntype = "{module_id}/token_type"\n\n'
        f'[output]\ntype = "{module_id}/token_type"\n'
    )
    composition = module / "compositions" / "token"
    composition.mkdir(parents=True)
    components = '[components]\nelement = "element"\n\n' if with_handler else ""
    (composition / "composition.toml").write_text(
        '[composition]\nid = "token"\n\n'
        + components
        + '[functions.echo.contract]\n'
        + f'use = "{module_id}/token"\n'
    )
    if with_handler:
        runtime = f'''\
from dataclasses import dataclass
from dix.core import ElementBinding, ElementIssue, ElementResult

@dataclass(frozen=True)
class Processor:
    def decode(self, raw):
        if isinstance(raw, str):
            return ElementResult(raw, True)
        return ElementResult(None, False, (ElementIssue("token_type", "token must be text"),))

@dataclass(frozen=True)
class Handler:
    handler_id = "{module_id}.token"
    def bind(self, spec, delegate):
        assert delegate is None
        return Processor()

class Runtime:
    def __init__(self, *, context, config, element):
        element.register_extension(ElementBinding(
            "{module_id}/token_type",
            Handler.handler_id,
            Handler(),
            "define",
        ))
    def echo(self, value):
        return value
'''
    else:
        runtime = (
            'class Runtime:\n'
            '    def __init__(self, *, context, config): pass\n'
            '    def echo(self, value): return value\n'
        )
    (composition / "runtime.py").write_text(runtime)
    return module


def test_custom_element_is_deferred_to_the_local_composition_scope(tmp_path: Path) -> None:
    modules, compositions, _ = core_components()
    missing_id = "acme/custom_missing"
    missing = write_custom_contract_module(
        tmp_path / "missing",
        module_id=missing_id,
        with_handler=False,
    )

    inspection = modules.inspect_module(missing, module_id=missing_id)
    assert inspection.contract_definitions[0].strand.input_element.type.endswith("token_type")
    modules.load_module(missing, module_id=missing_id)
    with pytest.raises(CompositionComponentError, match="unknown element type"):
        compositions.create_instance(
            CompositionInstanceSpec("token", f"{missing_id}/token", {}, missing),
            owner_scope_id="missing-handler",
        )

    modules, compositions, _ = core_components()
    local_id = "acme/custom_local"
    local = write_custom_contract_module(
        tmp_path / "local",
        module_id=local_id,
        with_handler=True,
    )
    modules.load_module(local, module_id=local_id)
    instance = compositions.create_instance(
        CompositionInstanceSpec("token", f"{local_id}/token", {}, local),
        owner_scope_id="local-handler",
    )
    assert asyncio.run(instance.api.invoke("echo", "value")) == "value"


def test_module_inspection_does_not_import_model_function_runtime(tmp_path: Path) -> None:
    module_id = "acme/no_import"
    root = write_model_function_module(tmp_path / "module", module_id=module_id)
    (root / "compositions" / "processor" / "runtime.py").write_text(
        'raise RuntimeError("inspection imported runtime")\n'
    )
    modules, _, _ = core_components()

    inspection = modules.inspect_module(root, module_id=module_id)

    assert len(inspection.model_definitions) == 1
    assert len(inspection.contract_definitions) == 1
    with pytest.raises(ModuleComponentError, match="inspection imported runtime"):
        modules.load_module(root, module_id=module_id)
