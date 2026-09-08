from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, dataclass
from typing import Any
from uuid import uuid4

import pytest

from dix.core import (
    NornComponent,
    DatamodelComponent,
    ElementBinding,
    ElementComponent,
    ElementProcessor,
    ElementResult,
    ModelDefinition,
    StrandDefinition,
    StrandDefinitionError,
    StrandExecutionError,
    StrandInputError,
    StrandNotBound,
    StrandNotFound,
    StrandOutputError,
    StrandRegistrationError,
    create_core_component_registry,
    model_definition,
    model_element,
)
from dix.core.element import ElementSpec, UnknownElementType


@dataclass(frozen=True)
class NumericStringProcessor:
    delegate: ElementProcessor

    def decode(self, raw: Any) -> ElementResult:
        value = int(raw) if isinstance(raw, str) and raw.isdecimal() else raw
        return self.delegate.decode(value)


@dataclass(frozen=True)
class NumericStringHandler:
    handler_id: str = "test.numeric_string"

    def bind(
        self,
        spec: ElementSpec,
        delegate: ElementProcessor | None,
    ) -> ElementProcessor:
        if delegate is None:
            raise AssertionError("numeric string handler requires a delegate")
        return NumericStringProcessor(delegate)


def model(name: str = "test/user") -> ModelDefinition:
    return ModelDefinition(
        uid=uuid4(),
        name=name,
        version="1",
        schema={
            "name": ElementSpec("string"),
            "age": ElementSpec("integer"),
        },
    )


def strand(
    strand_id: str = "test/text",
    *,
    input_type: str = "string",
    output_type: str = "string",
) -> StrandDefinition:
    return StrandDefinition(
        id=strand_id,
        input_element=ElementSpec(input_type),
        output_element=ElementSpec(output_type),
    )


def test_register_describe_bind_and_call_sync_handler() -> None:
    norn = create_core_component_registry().require("norn", NornComponent)
    registered = norn.register(strand())

    assert registered.definition.id == "test/text"
    assert norn.describe("test/text").bound is False
    assert norn.strands() == (norn.describe("test/text"),)

    binding = norn.bind(
        "test/text",
        handler_id="test.upper",
        handler=lambda value: value.upper(),
    )

    assert binding.handler_id == "test.upper"
    assert norn.describe("test/text").handler_id == "test.upper"
    assert asyncio.run(norn.call("test/text", "hello")) == "HELLO"


def test_async_handler_is_awaited() -> None:
    norn = create_core_component_registry().require("norn", NornComponent)
    norn.register(strand("test/async", input_type="integer", output_type="integer"))

    async def double(value: int) -> int:
        await asyncio.sleep(0)
        return value * 2

    norn.bind("test/async", handler_id="test.double", handler=double)

    assert asyncio.run(norn.call("test/async", 21)) == 42


def test_definition_and_descriptor_are_immutable_and_namespaced() -> None:
    definition = strand()
    descriptor = create_core_component_registry().require("norn", NornComponent)
    descriptor.register(definition)

    with pytest.raises(FrozenInstanceError):
        definition.id = "changed/id"  # type: ignore[misc]
    for invalid in ("", "plain", "one//two", "../two", "one/two three"):
        with pytest.raises(StrandDefinitionError, match="namespaced"):
            strand(invalid)
    with pytest.raises(StrandDefinitionError, match="must be an ElementSpec"):
        StrandDefinition("test/bad", "string", ElementSpec("string"))  # type: ignore[arg-type]


def test_registration_and_binding_fail_without_partial_publication() -> None:
    norn = create_core_component_registry().require("norn", NornComponent)

    with pytest.raises(UnknownElementType):
        norn.register(strand("test/unknown", input_type="missing"))
    assert norn.strands() == ()

    norn.register(strand())
    with pytest.raises(StrandRegistrationError, match="already registered"):
        norn.register(strand())
    with pytest.raises(StrandRegistrationError, match="handler_id"):
        norn.bind("test/text", handler_id="", handler=lambda value: value)
    assert norn.describe("test/text").bound is False

    norn.bind("test/text", handler_id="test.identity", handler=lambda value: value)
    with pytest.raises(StrandRegistrationError, match="already bound"):
        norn.bind("test/text", handler_id="test.identity", handler=lambda value: value)


def test_multiple_handlers_for_one_strand_are_explicitly_addressable() -> None:
    norn = create_core_component_registry().require("norn", NornComponent)
    norn.register(strand())
    norn.bind("test/text", handler_id="test.first", handler=lambda value: f"first:{value}")
    norn.bind("test/text", handler_id="test.second", handler=lambda value: f"second:{value}")

    assert norn.describe("test/text").handler_id is None
    with pytest.raises(StrandNotBound, match="multiple bindings"):
        asyncio.run(norn.call("test/text", "value"))
    assert asyncio.run(
        norn.call("test/text", "value", handler_id="test.first")
    ) == "first:value"
    assert asyncio.run(
        norn.call("test/text", "value", handler_id="test.second")
    ) == "second:value"


def test_unknown_unbound_input_and_output_fail_at_distinct_boundaries() -> None:
    norn = create_core_component_registry().require("norn", NornComponent)

    with pytest.raises(StrandNotFound):
        norn.describe("test/missing")

    calls: list[object] = []
    norn.register(strand("test/value", input_type="integer", output_type="string"))
    with pytest.raises(StrandNotBound):
        asyncio.run(norn.call("test/value", 1))

    def handler(value: object) -> object:
        calls.append(value)
        return 42

    norn.bind("test/value", handler_id="test.invalid_output", handler=handler)
    with pytest.raises(StrandInputError) as input_error:
        asyncio.run(norn.call("test/value", "1"))
    assert input_error.value.strand_id == "test/value"
    assert calls == []

    with pytest.raises(StrandOutputError) as output_error:
        asyncio.run(norn.call("test/value", 1))
    assert output_error.value.strand_id == "test/value"
    assert calls == [1]


def test_handler_error_preserves_context_and_cause() -> None:
    norn = create_core_component_registry().require("norn", NornComponent)
    norn.register(strand())

    def explode(value: object) -> object:
        raise RuntimeError(f"broken: {value}")

    norn.bind("test/text", handler_id="test.explode", handler=explode)

    with pytest.raises(StrandExecutionError) as error:
        asyncio.run(norn.call("test/text", "value"))
    assert error.value.strand_id == "test/text"
    assert error.value.handler_id == "test.explode"
    assert isinstance(error.value.__cause__, RuntimeError)


def test_norn_provider_is_composition_scoped() -> None:
    registry = create_core_component_registry()
    first = registry.create_scope("first").require("norn", NornComponent)
    second = registry.create_scope("second").require("norn", NornComponent)

    assert first is not second
    first.register(strand())
    first.bind("test/text", handler_id="first", handler=lambda value: f"first:{value}")
    second.register(strand())
    second.bind("test/text", handler_id="second", handler=lambda value: f"second:{value}")

    assert asyncio.run(first.call("test/text", "value")) == "first:value"
    assert asyncio.run(second.call("test/text", "value")) == "second:value"


def test_model_element_processes_complete_input_and_output_models() -> None:
    norn = create_core_component_registry().require("norn", NornComponent)
    input_model = model("test/input")
    output_model = ModelDefinition(
        uid=uuid4(),
        name="test/output",
        schema={"message": ElementSpec("string")},
    )
    seen: list[object] = []
    norn.register(
        StrandDefinition(
            "test/model",
            model_element(input_model),
            model_element(output_model),
        )
    )

    def handler(value: object) -> object:
        seen.append(value)
        return {"message": f"{value['name']}:{value['age']}"}  # type: ignore[index]

    norn.bind("test/model", handler_id="test.model", handler=handler)

    result = asyncio.run(norn.call("test/model", {"name": "Ada", "age": 42}))

    assert dict(result) == {"message": "Ada:42"}
    assert dict(seen[0]) == {"name": "Ada", "age": 42}  # type: ignore[arg-type]
    assert model_definition(norn.describe("test/model").input_element) is input_model


def test_model_element_reports_model_issues_at_the_strand_boundary() -> None:
    norn = create_core_component_registry().require("norn", NornComponent)
    norn.register(
        StrandDefinition(
            "test/model",
            model_element(model()),
            ElementSpec("string"),
        )
    )
    calls: list[object] = []
    norn.bind(
        "test/model",
        handler_id="test.model",
        handler=lambda value: calls.append(value) or "unused",
    )

    with pytest.raises(StrandInputError) as error:
        asyncio.run(norn.call("test/model", {"age": "old", "extra": True}))

    assert calls == []
    assert [(issue.details["field"], issue.code) for issue in error.value.issues] == [
        ("name", "missing_field"),
        ("extra", "additional_field"),
        ("age", "incompatible_type"),
    ]

    with pytest.raises(StrandInputError) as non_mapping:
        asyncio.run(norn.call("test/model", ["not", "a", "mapping"]))
    assert non_mapping.value.issues[0].code == "incompatible_model_value"


def test_model_element_rejects_incompatible_handler_output() -> None:
    norn = create_core_component_registry().require("norn", NornComponent)
    norn.register(
        StrandDefinition(
            "test/model-output",
            ElementSpec("string"),
            model_element(model("test/output")),
        )
    )
    norn.bind(
        "test/model-output",
        handler_id="test.invalid-model",
        handler=lambda value: {"name": value, "age": "unknown"},
    )

    with pytest.raises(StrandOutputError) as error:
        asyncio.run(norn.call("test/model-output", "Ada"))

    assert [(issue.details["field"], issue.code) for issue in error.value.issues] == [
        ("age", "incompatible_type"),
    ]


def test_model_element_uses_model_local_element_bindings() -> None:
    norn = create_core_component_registry().require("norn", NornComponent)
    wrapped = model_element(
        model(),
        elements=(
            ElementBinding(
                type_name="integer",
                handler_id="test.numeric_string",
                handler=NumericStringHandler(),
                mode="wrap",
            ),
        ),
    )
    seen: list[object] = []
    norn.register(StrandDefinition("test/wrapped", wrapped, ElementSpec("integer")))
    norn.bind(
        "test/wrapped",
        handler_id="test.age",
        handler=lambda value: seen.append(value) or value["age"],  # type: ignore[index]
    )

    assert asyncio.run(norn.call("test/wrapped", {"name": "Ada", "age": "42"})) == 42
    assert dict(seen[0])["age"] == 42  # type: ignore[arg-type]


def test_model_element_is_private_to_each_norn_scope() -> None:
    registry = create_core_component_registry()
    scope = registry.create_scope("model")
    element = scope.require("element", ElementComponent)
    datamodel = scope.require("datamodel", DatamodelComponent)
    norn = scope.require("norn", NornComponent)

    assert norn.datamodel is datamodel
    assert datamodel.registration_count == 0
    norn.register(
        StrandDefinition("test/model", model_element(model()), ElementSpec("string"))
    )
    assert datamodel.registration_count == 1
    with pytest.raises(UnknownElementType):
        element.bind(model_element(model()))
