from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from dix.models import ComponentDefinition, ComponentRuntime, ComponentSpec


class Component(ABC):
    definition: ComponentDefinition

    @abstractmethod
    def create_runtime(self, spec: ComponentSpec) -> ComponentRuntime:
        """Create renderer-independent runtime state for this component."""

    def update_runtime(
        self, spec: ComponentSpec, runtime: ComponentRuntime, data: dict[str, Any]
    ) -> ComponentRuntime:
        """Apply user-provided component data to renderer-independent state."""
        return runtime


def get_core_components() -> dict[str, Component]:
    from .input import InputComponent
    from .select import SelectComponent

    components: list[Component] = [InputComponent(), SelectComponent()]
    return {component.definition.id: component for component in components}
