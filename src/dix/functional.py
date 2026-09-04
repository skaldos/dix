from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from dix.core import CompositionComponent
from dix.core.composition import CompositionInstance, CompositionInstanceSpec
from dix.models import InterfaceSpec


class FunctionalInterfaceError(Exception):
    """Raised when a functional interface cannot be bound or invoked."""


class InterfaceFunctionNotFound(FunctionalInterfaceError):
    """Raised when an interface function ID is unknown."""


@dataclass(frozen=True)
class FunctionBinding:
    composition_id: str
    function_id: str


@dataclass(frozen=True)
class FunctionalInterfaceRuntime:
    interface_id: str
    owner_scope_id: str
    compositions: Mapping[str, CompositionInstance]
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
        try:
            return self.compositions[binding.composition_id].api.require(binding.function_id)()
        except Exception as exc:
            raise FunctionalInterfaceError(
                f"function '{function_id}' failed in interface '{self.interface_id}': {exc}"
            ) from exc


class FunctionalRuntimeStore:
    """Bind stable composition root graphs once per concrete interface source."""

    def __init__(self, compositions: CompositionComponent) -> None:
        self._composition_component = compositions
        self._items: dict[tuple[str, str], FunctionalInterfaceRuntime] = {}

    def get_or_create(self, spec: InterfaceSpec) -> FunctionalInterfaceRuntime:
        key = (spec.source or "<memory>", spec.interface.id)
        if key not in self._items:
            self._items[key] = self._bind(spec)
        return self._items[key]

    def _bind(self, spec: InterfaceSpec) -> FunctionalInterfaceRuntime:
        if spec.compositions and not spec.source:
            raise FunctionalInterfaceError(
                f"interface '{spec.interface.id}' requires an explicit source for composition config"
            )
        base_dir = Path(spec.source).resolve().parent if spec.source else Path("/")
        owner_scope_id = f"interface:{spec.source or '<memory>'}:{spec.interface.id}"
        bound: dict[str, CompositionInstance] = {}
        try:
            for composition in spec.compositions:
                instance = self._composition_component.create_instance(
                    CompositionInstanceSpec(
                        id=composition.id,
                        use=composition.use,
                        config=composition.config,
                        config_base_dir=base_dir,
                    ),
                    owner_scope_id=owner_scope_id,
                )
                self._composition_component.start_instance(owner_scope_id, composition.id)
                bound[composition.id] = instance
            functions: dict[str, FunctionBinding] = {}
            for function in spec.functions:
                composition_id, function_id = _parse_call(function.call, function.id)
                try:
                    target = bound[composition_id]
                except KeyError as exc:
                    raise FunctionalInterfaceError(
                        f"function '{function.id}' references unknown composition instance "
                        f"'{composition_id}'"
                    ) from exc
                try:
                    target.api.describe(function_id)
                except Exception as exc:
                    raise FunctionalInterfaceError(
                        f"function '{function.id}' references unknown function "
                        f"'{function_id}' on composition instance '{composition_id}'"
                    ) from exc
                functions[function.id] = FunctionBinding(
                    composition_id=composition_id,
                    function_id=function_id,
                )
            return FunctionalInterfaceRuntime(
                interface_id=spec.interface.id,
                owner_scope_id=owner_scope_id,
                compositions=bound,
                functions=functions,
            )
        except Exception as exc:
            for composition_id in reversed(tuple(bound)):
                try:
                    self._composition_component.destroy_instance(
                        owner_scope_id,
                        composition_id,
                    )
                except Exception:
                    pass
            if isinstance(exc, FunctionalInterfaceError):
                raise
            raise FunctionalInterfaceError(
                f"cannot bind interface '{spec.interface.id}': {exc}"
            ) from exc


def _parse_call(call: str, function_id: str) -> tuple[str, str]:
    parts = call.split(".")
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise FunctionalInterfaceError(
            f"function '{function_id}' call must be '<composition>.<function>'"
        )
    return parts[0].strip(), parts[1].strip()
