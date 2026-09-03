from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from dix.compositions import (
    BoundComposition,
    CompositionContext,
    CompositionError,
    CompositionRegistry,
)
from dix.core import ComponentRegistry
from dix.models import InterfaceSpec


class FunctionalInterfaceError(Exception):
    """Raised when a functional interface cannot be bound or invoked."""


class InterfaceFunctionNotFound(FunctionalInterfaceError):
    """Raised when an interface function ID is unknown."""


@dataclass(frozen=True)
class FunctionBinding:
    composition_id: str
    operation_id: str


@dataclass(frozen=True)
class FunctionalInterfaceRuntime:
    interface_id: str
    compositions: Mapping[str, BoundComposition]
    functions: Mapping[str, FunctionBinding]

    def __post_init__(self) -> None:
        object.__setattr__(self, "compositions", MappingProxyType(dict(self.compositions)))
        object.__setattr__(self, "functions", MappingProxyType(dict(self.functions)))

    def invoke(self, function_id: str) -> Any:
        try:
            binding = self.functions[function_id]
        except KeyError as exc:
            raise InterfaceFunctionNotFound(
                f"function not found in interface '{self.interface_id}': {function_id}"
            ) from exc
        return self.compositions[binding.composition_id].invoke(binding.operation_id)


class FunctionalRuntimeStore:
    """Binds trusted compositions once per concrete interface source."""

    def __init__(
        self,
        components: ComponentRegistry,
        compositions: CompositionRegistry,
    ) -> None:
        self._components = components
        self._composition_registry = compositions
        self._items: dict[tuple[str, str], FunctionalInterfaceRuntime] = {}

    def get_or_create(self, spec: InterfaceSpec) -> FunctionalInterfaceRuntime:
        key = (spec.source or "<memory>", spec.interface.id)
        if key not in self._items:
            self._items[key] = self._bind(spec)
        return self._items[key]

    def _bind(self, spec: InterfaceSpec) -> FunctionalInterfaceRuntime:
        base_dir = Path(spec.source).resolve().parent if spec.source else Path.cwd().resolve()
        context = CompositionContext(components=self._components, base_dir=base_dir)
        bound: dict[str, BoundComposition] = {}
        try:
            for composition in spec.compositions:
                bound[composition.id] = self._composition_registry.bind(
                    composition.use,
                    context,
                    composition.config,
                )
        except CompositionError as exc:
            raise FunctionalInterfaceError(
                f"cannot bind interface '{spec.interface.id}': {exc}"
            ) from exc

        functions: dict[str, FunctionBinding] = {}
        for function in spec.functions:
            composition_id, operation_id = _parse_call(function.call, function.id)
            try:
                target = bound[composition_id]
            except KeyError as exc:
                raise FunctionalInterfaceError(
                    f"function '{function.id}' references unknown composition instance "
                    f"'{composition_id}'"
                ) from exc
            if operation_id not in target.operations:
                raise FunctionalInterfaceError(
                    f"function '{function.id}' references unknown operation "
                    f"'{operation_id}' on composition instance '{composition_id}'"
                )
            functions[function.id] = FunctionBinding(
                composition_id=composition_id,
                operation_id=operation_id,
            )

        return FunctionalInterfaceRuntime(
            interface_id=spec.interface.id,
            compositions=bound,
            functions=functions,
        )


def _parse_call(call: str, function_id: str) -> tuple[str, str]:
    parts = call.split(".")
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise FunctionalInterfaceError(
            f"function '{function_id}' call must be '<composition>.<operation>'"
        )
    return parts[0].strip(), parts[1].strip()
