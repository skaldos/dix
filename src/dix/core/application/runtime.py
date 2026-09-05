from __future__ import annotations

import inspect
from collections.abc import Mapping

from .models import (
    ApplicationDefinition,
    ApplicationFunctionDescriptor,
)


class ApplicationRuntimeError(Exception):
    """Raised when loaded application runtime code violates its declared contract."""


def validate_runtime_constructor(runtime_type: type[object], aliases: tuple[str, ...]) -> None:
    """Require one keyword-only constructor with exactly the declared dependencies."""
    signature = inspect.signature(runtime_type.__init__)
    parameters = [parameter for name, parameter in signature.parameters.items() if name != "self"]
    expected = ("context", "config", *aliases)
    actual = tuple(parameter.name for parameter in parameters)
    if actual != expected:
        raise ApplicationRuntimeError(
            f"application Runtime.__init__ parameters must be {expected}, got {actual}"
        )
    invalid = [
        parameter.name
        for parameter in parameters
        if parameter.kind is not inspect.Parameter.KEYWORD_ONLY
    ]
    if invalid:
        raise ApplicationRuntimeError(
            "application Runtime.__init__ parameters must be keyword-only: " + ", ".join(invalid)
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
