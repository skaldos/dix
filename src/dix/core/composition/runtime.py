from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from types import MappingProxyType

from dix.core.contract import (
    ContractDefinition,
    ContractReference,
    resolve_contract_strand,
)
from dix.core.function import (
    FunctionDescriptor,
    FunctionRuntimeBinding,
    bind_function,
    bind_function_runtime,
    invoke_function,
)
from dix.core.model import ModelArtifactDefinition, ModelReference
from dix.core.norn import NornComponent

from .models import (
    CompositionDefinition,
    CompositionFunctionDescriptor,
    CompositionFunctionSpec,
)


class CompositionRuntimeError(Exception):
    """Raised when a runtime class does not satisfy its declared composition contract."""


class CompositionApi:
    """Restricted facade over the declared functions of one runtime instance."""

    def __init__(
        self,
        functions: Mapping[str, Callable[..., object]],
        descriptors: Mapping[str, CompositionFunctionDescriptor],
        runtime_bindings: Mapping[str, FunctionRuntimeBinding],
        norn: NornComponent,
    ) -> None:
        self._functions = MappingProxyType(dict(functions))
        self._descriptors = MappingProxyType(dict(descriptors))
        self._runtime_bindings = MappingProxyType(dict(runtime_bindings))
        self._norn = norn

    def require(self, function_id: str) -> Callable[..., object]:
        try:
            return self._functions[function_id]
        except KeyError as exc:
            raise CompositionRuntimeError(
                f"composition function is not declared: {function_id}"
            ) from exc

    def describe(self, function_id: str) -> CompositionFunctionDescriptor:
        try:
            return self._descriptors[function_id]
        except KeyError as exc:
            raise CompositionRuntimeError(
                f"composition function is not declared: {function_id}"
            ) from exc

    def functions(self) -> tuple[CompositionFunctionDescriptor, ...]:
        return tuple(self._descriptors[item] for item in sorted(self._descriptors))

    async def invoke(self, function_id: str, value: object) -> object:
        self.describe(function_id)
        return await invoke_function(
            self._runtime_bindings[function_id],
            value,
            norn=self._norn,
        )

    def __getattr__(self, function_id: str) -> Callable[..., object]:
        if function_id.startswith("_"):
            raise AttributeError(function_id)
        try:
            return self.require(function_id)
        except CompositionRuntimeError as exc:
            raise AttributeError(function_id) from exc


def validate_runtime_constructor(runtime_type: type[object], aliases: tuple[str, ...]) -> None:
    expected = ("context", "config", *aliases)
    signature = inspect.signature(runtime_type.__init__)
    parameters = tuple(signature.parameters.values())[1:]
    actual = tuple(parameter.name for parameter in parameters)
    invalid_kinds = [
        parameter.name
        for parameter in parameters
        if parameter.kind is not inspect.Parameter.KEYWORD_ONLY
    ]
    if set(actual) != set(expected) or len(actual) != len(expected) or invalid_kinds:
        raise CompositionRuntimeError(
            f"Runtime constructor must contain exactly the keyword-only parameters "
            f"{expected!r}; got {signature}"
        )


def function_origins(
    definition: CompositionDefinition,
) -> dict[str, tuple[str, CompositionFunctionSpec | None]]:
    origins: dict[str, tuple[str, CompositionFunctionSpec | None]] = {}
    for function_id, function in definition.functions.items():
        origins[function_id] = (function.export or "", function)
    return origins


def describe_runtime_functions(
    definition: CompositionDefinition,
    runtime_type: type[object],
    contracts: Mapping[ContractReference, ContractDefinition],
    models: Mapping[ModelReference, ModelArtifactDefinition],
) -> tuple[CompositionFunctionDescriptor, ...]:
    descriptors: list[CompositionFunctionDescriptor] = []
    for function_id, (origin_value, function_spec) in sorted(
        function_origins(definition).items()
    ):
        if function_spec is None:
            raise CompositionRuntimeError(
                f"composition function requires an explicit contract: "
                f"{definition.id}.{function_id}"
            )
        raw_method = runtime_type.__dict__.get(function_id)
        if not inspect.isfunction(raw_method):
            raise CompositionRuntimeError(
                f"composition '{definition.id}' must define wrapper method "
                f"Runtime.{function_id}"
            )
        signature = inspect.signature(raw_method)
        parameters = tuple(signature.parameters.values())
        if not parameters or parameters[0].name != "self":
            raise CompositionRuntimeError(
                f"composition function Runtime.{function_id} must be an instance method"
            )
        public_signature = signature.replace(parameters=parameters[1:])
        origin = origin_value or None
        try:
            contract = contracts[function_spec.contract]
        except KeyError as exc:
            reference = function_spec.contract
            raise CompositionRuntimeError(
                f"composition function contract is not loaded: "
                f"{definition.id}.{function_id} -> {reference.use}@{reference.version!r}"
            ) from exc
        function = FunctionDescriptor(
            id=function_id,
            owner_id=definition.id,
            source="local_wrapper" if origin is not None else "local",
            origin=origin,
            signature=public_signature,
            return_annotation=public_signature.return_annotation,
            docstring=inspect.getdoc(raw_method),
            is_async=inspect.iscoroutinefunction(raw_method),
        )
        descriptors.append(
            CompositionFunctionDescriptor(
                **function.__dict__,
                binding=bind_function(
                    function,
                    contract,
                    strand=resolve_contract_strand(contract, models),
                ),
            )
        )
    return tuple(descriptors)


def create_api(
    definition: CompositionDefinition,
    runtime: object,
    dependencies: Mapping[str, CompositionApi],
    descriptors: tuple[CompositionFunctionDescriptor, ...],
    norn: NornComponent,
) -> CompositionApi:
    functions: dict[str, Callable[..., object]] = {}
    runtime_bindings: dict[str, FunctionRuntimeBinding] = {}
    for descriptor in descriptors:
        if descriptor.origin is not None:
            alias, dependency_function = descriptor.origin.split(".", 1)
            try:
                dependency_api = dependencies[alias]
            except KeyError as exc:
                raise CompositionRuntimeError(
                    f"wrapper origin uses unknown dependency alias: {descriptor.origin}"
                ) from exc
            dependency_api.describe(dependency_function)
        bound = getattr(runtime, descriptor.id)
        if not callable(bound):
            raise CompositionRuntimeError(
                f"composition function is not callable: {definition.id}.{descriptor.id}"
            )
        functions[descriptor.id] = bound
        runtime_bindings[descriptor.id] = bind_function_runtime(
            descriptor.binding,
            bound,
            norn=norn,
        )
    return CompositionApi(
        functions=functions,
        descriptors={item.id: item for item in descriptors},
        runtime_bindings=runtime_bindings,
        norn=norn,
    )
