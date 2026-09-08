from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING

from .models import (
    ApplicationDefinition,
    ApplicationFunctionDescriptor,
)

if TYPE_CHECKING:
    from dix.core.composition import CompositionApi


class ApplicationRuntimeError(Exception):
    """Raised when loaded application runtime code violates its declared contract."""


class ApplicationApi:
    """Restricted facade over the declared functions of one application instance."""

    def __init__(
        self,
        functions: Mapping[str, Callable[..., object]],
        descriptors: Mapping[str, ApplicationFunctionDescriptor],
    ) -> None:
        self._functions = MappingProxyType(dict(functions))
        self._descriptors = MappingProxyType(dict(descriptors))

    def require(self, function_id: str) -> Callable[..., object]:
        try:
            return self._functions[function_id]
        except KeyError as exc:
            raise ApplicationRuntimeError(
                f"application function is not declared: {function_id}"
            ) from exc

    def describe(self, function_id: str) -> ApplicationFunctionDescriptor:
        try:
            return self._descriptors[function_id]
        except KeyError as exc:
            raise ApplicationRuntimeError(
                f"application function is not declared: {function_id}"
            ) from exc

    def functions(self) -> tuple[ApplicationFunctionDescriptor, ...]:
        return tuple(self._descriptors[item] for item in sorted(self._descriptors))

    def __getattr__(self, function_id: str) -> Callable[..., object]:
        if function_id.startswith("_"):
            raise AttributeError(function_id)
        try:
            return self.require(function_id)
        except ApplicationRuntimeError as exc:
            raise AttributeError(function_id) from exc


def validate_runtime_constructor(runtime_type: type[object], aliases: tuple[str, ...]) -> None:
    """Require one keyword-only constructor with exactly the declared dependencies."""
    signature = inspect.signature(runtime_type.__init__)
    parameters = [parameter for name, parameter in signature.parameters.items() if name != "self"]
    expected = ("context", "config", *aliases)
    actual = tuple(parameter.name for parameter in parameters)
    invalid = [
        parameter.name
        for parameter in parameters
        if parameter.kind is not inspect.Parameter.KEYWORD_ONLY
    ]
    if set(actual) != set(expected) or len(actual) != len(expected) or invalid:
        raise ApplicationRuntimeError(
            "application Runtime.__init__ must contain exactly the keyword-only parameters "
            f"{expected!r}; got {signature}"
        )


def function_origins(definition: ApplicationDefinition) -> Mapping[str, str | None]:
    origins: dict[str, str | None] = {}
    for alias, dependency in definition.compositions.items():
        for function_id in dependency.export:
            origins[function_id] = f"{alias}.{function_id}"
    for alias, dependency in definition.applications.items():
        for function_id in dependency.export:
            origins[function_id] = f"{alias}.{function_id}"
    for function_id, function in definition.functions.items():
        origins[function_id] = function.export
    return origins


def describe_runtime_functions(
    definition: ApplicationDefinition,
    runtime_type: type[object],
) -> tuple[ApplicationFunctionDescriptor, ...]:
    """Describe only functions declared by the application spec."""
    origins = function_origins(definition)
    descriptors: list[ApplicationFunctionDescriptor] = []
    for function_id in sorted(origins):
        function = runtime_type.__dict__.get(function_id)
        if not inspect.isfunction(function):
            raise ApplicationRuntimeError(
                f"application runtime '{definition.id}' does not implement declared function "
                f"'{function_id}'"
            )
        signature = inspect.signature(function)
        parameters = tuple(signature.parameters.values())
        if not parameters or parameters[0].name != "self":
            raise ApplicationRuntimeError(
                f"application function must be an instance method: {definition.id}.{function_id}"
            )
        public_signature = signature.replace(parameters=parameters[1:])
        origin = origins[function_id]
        descriptors.append(
            ApplicationFunctionDescriptor(
                id=function_id,
                application_id=definition.id,
                source="local_wrapper" if origin is not None else "local",
                origin=origin,
                signature=public_signature,
                return_annotation=public_signature.return_annotation,
                docstring=inspect.getdoc(function),
                is_async=inspect.iscoroutinefunction(function),
            )
        )
    return tuple(descriptors)


def create_api(
    definition: ApplicationDefinition,
    runtime: object,
    composition_dependencies: Mapping[str, CompositionApi],
    application_dependencies: Mapping[str, ApplicationApi],
) -> ApplicationApi:
    descriptors = describe_runtime_functions(definition, type(runtime))
    dependencies = {**composition_dependencies, **application_dependencies}
    functions: dict[str, Callable[..., object]] = {}
    for descriptor in descriptors:
        if descriptor.origin is not None:
            alias, dependency_function = descriptor.origin.split(".", 1)
            try:
                dependency_api = dependencies[alias]
            except KeyError as exc:
                raise ApplicationRuntimeError(
                    f"wrapper origin uses unknown dependency alias: {descriptor.origin}"
                ) from exc
            dependency_api.describe(dependency_function)
        bound = getattr(runtime, descriptor.id)
        if not callable(bound):
            raise ApplicationRuntimeError(
                f"application function is not callable: {definition.id}.{descriptor.id}"
            )
        functions[descriptor.id] = bound
    return ApplicationApi(
        functions=functions,
        descriptors={item.id: item for item in descriptors},
    )
