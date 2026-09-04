from __future__ import annotations

from dataclasses import dataclass

import pytest

from dix.core import (
    ComponentProvider,
    ComponentRegistry,
    ComponentRegistryError,
    DatamodelComponent,
    ElementComponent,
    create_core_component_registry,
)


@dataclass
class DemoComponent:
    value: str = "demo"


def provider(
    component_id: str = "demo",
    *,
    lifetime: str = "composition",
) -> ComponentProvider:
    return ComponentProvider(
        id=component_id,
        lifetime=lifetime,  # type: ignore[arg-type]
        create=lambda scope: DemoComponent(scope.id),
    )


def test_composition_lifetime_is_cached_only_within_one_scope() -> None:
    registry = ComponentRegistry()
    registry.register_provider(provider())
    first_scope = registry.create_scope("first")
    second_scope = registry.create_scope("second")

    first = first_scope.require("demo", DemoComponent)

    assert first_scope.require("demo", DemoComponent) is first
    assert second_scope.require("demo", DemoComponent) is not first
    assert second_scope.require("demo", DemoComponent).value == "second"


def test_runtime_lifetime_is_shared_across_scopes() -> None:
    registry = ComponentRegistry()
    registry.register_provider(provider(lifetime="runtime"))

    first = registry.create_scope("first").require("demo", DemoComponent)
    second = registry.create_scope("second").require("demo", DemoComponent)

    assert second is first


def test_registry_provider_metadata_and_ids_are_deterministic() -> None:
    registry = ComponentRegistry()
    registry.register_provider(provider("z-last"))
    registry.register_provider(provider("a-first", lifetime="runtime"))

    assert registry.ids() == ("a-first", "z-last")
    assert [(item.id, item.lifetime) for item in registry.providers()] == [
        ("a-first", "runtime"),
        ("z-last", "composition"),
    ]


def test_registry_rejects_duplicates_missing_and_wrong_types() -> None:
    registry = ComponentRegistry()
    registry.register_provider(provider())

    with pytest.raises(ComponentRegistryError, match="already registered"):
        registry.register_provider(provider())
    with pytest.raises(ComponentRegistryError, match="not found"):
        registry.require("missing", DemoComponent)
    with pytest.raises(ComponentRegistryError, match="expected dict"):
        registry.require("demo", dict)
    with pytest.raises(ComponentRegistryError, match="must be a ComponentProvider"):
        registry.register_provider(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("component_id", "lifetime", "message"),
    [
        (" ", "composition", "must not be empty"),
        ("demo", "request", "invalid lifetime"),
    ],
)
def test_provider_rejects_invalid_metadata(
    component_id: str,
    lifetime: str,
    message: str,
) -> None:
    with pytest.raises(ComponentRegistryError, match=message):
        provider(component_id, lifetime=lifetime)


def test_provider_dependencies_resolve_in_the_same_scope() -> None:
    registry = create_core_component_registry()
    first_scope = registry.create_scope("first")
    second_scope = registry.create_scope("second")

    first_model = first_scope.require("datamodel", DatamodelComponent)
    first_element = first_scope.require("element", ElementComponent)
    second_model = second_scope.require("datamodel", DatamodelComponent)
    second_element = second_scope.require("element", ElementComponent)

    assert first_model.element is first_element
    assert second_model.element is second_element
    assert first_model is not second_model
    assert first_element is not second_element


def test_direct_core_require_uses_one_stable_root_scope() -> None:
    registry = create_core_component_registry()

    first = registry.require("datamodel", DatamodelComponent)

    assert registry.require("datamodel", DatamodelComponent) is first
    assert first.element is registry.require("element", ElementComponent)


def test_component_provider_cycle_reports_the_complete_path() -> None:
    registry = ComponentRegistry()
    registry.register_provider(
        ComponentProvider(
            id="first",
            lifetime="composition",
            create=lambda scope: scope.require("second", DemoComponent),
        )
    )
    registry.register_provider(
        ComponentProvider(
            id="second",
            lifetime="composition",
            create=lambda scope: scope.require("first", DemoComponent),
        )
    )

    with pytest.raises(
        ComponentRegistryError,
        match="first -> second -> first",
    ):
        registry.create_scope("cycle").require("first", DemoComponent)
