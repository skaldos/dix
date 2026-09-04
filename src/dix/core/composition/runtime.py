from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from types import MappingProxyType

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
    ) -> None:
        self._functions = MappingProxyType(dict(functions))
        self._descriptors = MappingProxyType(dict(descriptors))

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
    if actual != expected or invalid_kinds:
        raise CompositionRuntimeError(
            f"Runtime constructor for dependencies {expected!r} must contain exactly "
            f"keyword-only parameters in that order; got {signature}"
        )


def function_origins(
    definition: CompositionDefinition,
) -> dict[str, tuple[str, CompositionFunctionSpec | None]]:
    origins: dict[str, tuple[str, CompositionFunctionSpec | None]] = {}
    for alias, dependency in definition.compositions.items():
        for function_id in dependency.export:
            origins[function_id] = (f"{alias}.{function_id}", None)
    for function_id, function in definition.functions.items():
        origins[function_id] = (function.export or "", function)
    return origins


def describe_runtime_functions(
    definition: CompositionDefinition,
    runtime_type: type[object],
) -> tuple[CompositionFunctionDescriptor, ...]:
    descriptors: list[CompositionFunctionDescriptor] = []
    for function_id, (origin_value, function_spec) in sorted(
        function_origins(definition).items()
    ):
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
        descriptors.append(
            CompositionFunctionDescriptor(
                id=function_id,
                composition_id=definition.id,
                source="local_wrapper" if origin is not None else "local",
                origin=origin,
                signature=public_signature,
                return_annotation=public_signature.return_annotation,
                docstring=inspect.getdoc(raw_method)
                or (function_spec.description if function_spec is not None else None),
                is_async=inspect.iscoroutinefunction(raw_method),
            )
        )
    return tuple(descriptors)


def create_api(
    definition: CompositionDefinition,
    runtime: object,
    dependencies: Mapping[str, CompositionApi],
) -> CompositionApi:
    descriptors = describe_runtime_functions(definition, type(runtime))
    functions: dict[str, Callable[..., object]] = {}
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
    return CompositionApi(
        functions=functions,
        descriptors={item.id: item for item in descriptors},
    )
