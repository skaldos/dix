from __future__ import annotations

from typing import Protocol, runtime_checkable


class ComponentRegistryError(Exception):
    """Raised when a core component cannot be registered or resolved."""


@runtime_checkable
class IdentifiedComponent(Protocol):
    component_id: str


class ComponentRegistry:
    """Registry of stable, explicitly assembled component instances."""

    def __init__(self) -> None:
        self._components: dict[str, object] = {}

    def register(self, component: IdentifiedComponent) -> None:
        raw_component_id = getattr(component, "component_id", None)
        if not isinstance(raw_component_id, str):
            raise ComponentRegistryError("component must define a string component_id")
        component_id = raw_component_id.strip()
        if not component_id:
            raise ComponentRegistryError("component_id must not be empty")
        if component_id in self._components:
            raise ComponentRegistryError(f"component already registered: {component_id}")
        self._components[component_id] = component

    def require[T](self, component_id: str, expected_type: type[T]) -> T:
        try:
            component = self._components[component_id]
        except KeyError as exc:
            raise ComponentRegistryError(f"component not found: {component_id}") from exc
        if not isinstance(component, expected_type):
            raise ComponentRegistryError(
                f"component '{component_id}' has type {type(component).__name__}, "
                f"expected {expected_type.__name__}"
            )
        return component

    def ids(self) -> tuple[str, ...]:
        return tuple(self._components)
