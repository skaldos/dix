from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from dix.core import (
    ContractDefinition,
    ElementSpec,
    FunctionBindingError,
    FunctionDescriptor,
    FunctionExecutionError,
    FunctionInputError,
    FunctionOutputError,
    NornComponent,
    StrandDefinition,
    bind_function,
    bind_function_runtime,
    create_core_component_registry,
    invoke_function,
)
from dix.core.function import FunctionBinding, FunctionRuntimeBinding


def contract(input_type: str = "string", output_type: str = "string") -> ContractDefinition:
    strand = StrandDefinition(
        id="acme/contracts/echo",
        input_element=ElementSpec(input_type),
        output_element=ElementSpec(output_type),
    )
    return ContractDefinition(
        id=strand.id,
        local_id="echo",
        module_id="acme/contracts",
        version="1",
        strand=strand,
        spec_path=Path("contract.toml"),
    )


def descriptor(target, *, identifier: str = "echo") -> FunctionDescriptor:
    return FunctionDescriptor(
        id=identifier,
        owner_id="acme/tool",
        source="local",
        origin=None,
        signature=inspect.signature(target),
        return_annotation=inspect.signature(target).return_annotation,
        docstring=inspect.getdoc(target),
        is_async=inspect.iscoroutinefunction(target),
    )


def runtime_binding(
    binding: FunctionBinding,
    target,
) -> tuple[NornComponent, FunctionRuntimeBinding]:
    norn = create_core_component_registry().require("norn", NornComponent)
    return norn, bind_function_runtime(binding, target, norn=norn)


def test_sync_function_is_invoked_through_authoritative_contract() -> None:
    def echo(value: str) -> str:
        return value

    binding = bind_function(descriptor(echo), contract())
    norn, runtime = runtime_binding(binding, echo)

    assert asyncio.run(invoke_function(
        runtime,
        "hello",
        norn=norn,
    )) == "hello"


def test_async_keyword_only_function_is_supported() -> None:
    async def echo(*, value: str) -> str:
        return value

    binding = bind_function(descriptor(echo), contract())
    norn, runtime = runtime_binding(binding, echo)

    assert asyncio.run(invoke_function(
        runtime,
        "hello",
        norn=norn,
    )) == "hello"


@pytest.mark.parametrize(
    "target",
    [
        lambda: None,
        lambda first, second: None,
        lambda *values: None,
        lambda **values: None,
    ],
)
def test_unsupported_function_shapes_fail_explicitly(target) -> None:
    with pytest.raises(FunctionBindingError):
        bind_function(descriptor(target), contract())


def test_invalid_input_prevents_target_call() -> None:
    calls: list[object] = []

    def echo(value: str) -> str:
        calls.append(value)
        return value

    binding = bind_function(descriptor(echo), contract())
    norn, runtime = runtime_binding(binding, echo)

    with pytest.raises(FunctionInputError):
        asyncio.run(invoke_function(
            runtime,
            42,
            norn=norn,
        ))
    assert calls == []


def test_invalid_output_is_rejected_after_target_call() -> None:
    def echo(value: str) -> int:
        return len(value)

    binding = bind_function(descriptor(echo), contract())
    norn, runtime = runtime_binding(binding, echo)

    with pytest.raises(FunctionOutputError):
        asyncio.run(invoke_function(
            runtime,
            "hello",
            norn=norn,
        ))


def test_target_failure_preserves_cause() -> None:
    failure = RuntimeError("target failed")

    def echo(value: str) -> str:
        raise failure

    binding = bind_function(descriptor(echo), contract())
    norn, runtime = runtime_binding(binding, echo)

    with pytest.raises(FunctionExecutionError) as captured:
        asyncio.run(invoke_function(
            runtime,
            "hello",
            norn=norn,
        ))
    assert captured.value.__cause__ is failure
