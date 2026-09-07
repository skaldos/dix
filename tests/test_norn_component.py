from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError

import pytest

from dix.core import (
    NornComponent,
    StrandDefinition,
    StrandDefinitionError,
    StrandExecutionError,
    StrandInputError,
    StrandNotBound,
    StrandNotFound,
    StrandOutputError,
    StrandRegistrationError,
    create_core_component_registry,
)
from dix.core.element import ElementSpec, UnknownElementType


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
        norn.bind("test/text", handler_id="test.other", handler=lambda value: value)


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
