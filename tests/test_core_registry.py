from __future__ import annotations

from dataclasses import dataclass

import pytest

from dix.core import ComponentRegistry, ComponentRegistryError


@dataclass
class DemoComponent:
    component_id: str = "demo"


def test_component_registry_returns_the_same_instance() -> None:
    component = DemoComponent()
    registry = ComponentRegistry()
    registry.register(component)

    assert registry.require("demo", DemoComponent) is component
    assert registry.ids() == ("demo",)


def test_component_registry_rejects_duplicates_missing_and_wrong_types() -> None:
    registry = ComponentRegistry()
    registry.register(DemoComponent())

    with pytest.raises(ComponentRegistryError, match="already registered"):
        registry.register(DemoComponent())
    with pytest.raises(ComponentRegistryError, match="not found"):
        registry.require("missing", DemoComponent)
    with pytest.raises(ComponentRegistryError, match="expected dict"):
        registry.require("demo", dict)
    with pytest.raises(ComponentRegistryError, match="string component_id"):
        registry.register(object())  # type: ignore[arg-type]
