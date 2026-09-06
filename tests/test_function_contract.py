from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from dix.core import (
    ApplicationComponent,
    CompositionComponent,
    DatamodelComponent,
    ModuleComponent,
    create_core_component_registry,
    derive_function_contract,
)
from dix.core.application import ApplicationInstanceSpec
from dix.core.composition import CompositionInstanceSpec

REPOSITORY = Path(__file__).resolve().parents[1]
CLI_DEMO_MODULE = REPOSITORY / "examples" / "modules" / "acme" / "cli_demo"
CLI_MODULE = REPOSITORY / "examples" / "modules" / "dix" / "core" / "cli"
APP_MODULE = REPOSITORY / "examples" / "modules" / "dix" / "core" / "app"


def test_signature_projection_preserves_parameter_semantics_and_falls_back_safely() -> None:
    def target(
        positional: str,
        /,
        count: int = 2,
        *values: float,
        enabled: bool,
        unknown: list[str] | None = None,
        **metadata: Any,
    ) -> str:
        return positional

    contract = derive_function_contract("test/tool", "target", inspect.signature(target))

    assert tuple(contract.input_model.schema) == (
        "positional",
        "count",
        "values",
        "enabled",
        "unknown",
        "metadata",
    )
    assert [parameter.kind for parameter in contract.parameters] == [
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.VAR_POSITIONAL,
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.VAR_KEYWORD,
    ]
    assert [parameter.element_type for parameter in contract.parameters] == [
        "string",
        "integer",
        "any",
        "boolean",
        "any",
        "any",
    ]
    assert [parameter.projection for parameter in contract.parameters] == [
        "exact",
        "exact",
        "fallback_any",
        "exact",
        "fallback_any",
        "fallback_any",
    ]
    assert [parameter.required for parameter in contract.parameters] == [
        True,
        False,
        False,
        True,
        False,
        False,
    ]
    assert contract.parameters[1].default == 2
    assert contract.parameters[4].annotation == "list[str] | None"
    assert contract.output.element.type == "string"
    assert contract.output.projection == "exact"


def test_contract_model_is_immutable_and_unknown_return_uses_any() -> None:
    class Result:
        pass

    def target(value) -> Result:
        return Result()

    contract = derive_function_contract("test/tool", "target", inspect.signature(target))

    assert contract.input_model.schema["value"].type == "any"
    assert contract.parameters[0].annotation is inspect.Signature.empty
    assert contract.output.element.type == "any"
    assert contract.output.annotation == "Result"
    with pytest.raises(TypeError):
        contract.input_model.schema["extra"] = contract.input_model.schema["value"]  # type: ignore[index]


def test_native_value_annotations_project_to_extended_core_elements() -> None:
    signature = inspect.Signature(
        parameters=(
            inspect.Parameter("nothing", inspect.Parameter.KEYWORD_ONLY, annotation=type(None)),
            inspect.Parameter("ratio", inspect.Parameter.KEYWORD_ONLY, annotation=float),
            inspect.Parameter("payload", inspect.Parameter.KEYWORD_ONLY, annotation=bytes),
            inspect.Parameter("items", inspect.Parameter.KEYWORD_ONLY, annotation=list),
            inspect.Parameter("attributes", inspect.Parameter.KEYWORD_ONLY, annotation=dict),
        ),
        return_annotation=None,
    )

    contract = derive_function_contract("test/tool", "native", signature)

    assert [parameter.element_type for parameter in contract.parameters] == [
        "null",
        "number",
        "binary",
        "array",
        "object",
    ]
    assert [parameter.projection for parameter in contract.parameters] == ["exact"] * 5
    assert contract.output.element.type == "null"
    assert contract.output.projection == "exact"


def test_parameterized_native_containers_remain_honest_fallbacks() -> None:
    def target(*, items: list[str], attributes: dict[str, int]) -> list[str]:
        return items

    contract = derive_function_contract("test/tool", "containers", inspect.signature(target))

    assert [parameter.element_type for parameter in contract.parameters] == ["any", "any"]
    assert [parameter.projection for parameter in contract.parameters] == [
        "fallback_any",
        "fallback_any",
    ]
    assert contract.output.element.type == "any"
    assert contract.output.projection == "fallback_any"


def test_loaded_application_reuses_one_descriptor_and_contract_identity() -> None:
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    modules.load_module(APP_MODULE, module_id="dix/core/app")
    modules.load_module(CLI_MODULE, module_id="dix/core/cli")
    modules.load_module(CLI_DEMO_MODULE, module_id="acme/cli_demo")
    applications = registry.require("application", ApplicationComponent)

    first = applications.describe_function("acme/cli_demo/tool", "render")
    second = applications.describe_function("acme/cli_demo/tool", "render")
    instance = applications.create_instance(
        ApplicationInstanceSpec("tool", "acme/cli_demo/tool", {}, REPOSITORY),
        owner_scope_id="contract",
    )

    assert first is second
    assert first.contract is second.contract
    assert first.contract.input_model.uid == second.contract.input_model.uid
    assert instance.api.describe("render") is first
    assert first.contract.input_model.schema == {
        "value": first.contract.input_model.schema["value"],
        "count": first.contract.input_model.schema["count"],
        "upper": first.contract.input_model.schema["upper"],
    }


def test_loaded_composition_reuses_one_descriptor_and_contract_identity() -> None:
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    modules.load_module(APP_MODULE, module_id="dix/core/app")
    modules.load_module(CLI_MODULE, module_id="dix/core/cli")
    compositions = registry.require("composition", CompositionComponent)

    first = compositions.describe_function("dix/core/cli/typer_cli", "invoke")
    second = compositions.describe_function("dix/core/cli/typer_cli", "invoke")
    instance = compositions.create_instance(
        CompositionInstanceSpec("cli", "dix/core/cli/typer_cli", {}, REPOSITORY),
        owner_scope_id="contract",
    )

    assert first is second
    assert first.contract is second.contract
    assert first.contract.input_model.uid == second.contract.input_model.uid
    assert instance.api.describe("invoke") is first
    assert registry.require("datamodel", DatamodelComponent).registration_count == 0
