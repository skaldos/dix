from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

ComponentLifetime = Literal["composition", "runtime"]


class ComponentRegistryError(Exception):
    """Raised when a core component provider or instance cannot be resolved."""


@dataclass(frozen=True)
class ComponentProvider:
    """Describe how one component is created and how long it is shared."""

    id: str
    lifetime: ComponentLifetime
    create: Callable[[ComponentScope], object]

    def __post_init__(self) -> None:
        component_id = self.id.strip()
        if not component_id:
            raise ComponentRegistryError("component provider id must not be empty")
        if self.lifetime not in ("composition", "runtime"):
            raise ComponentRegistryError(
                f"component provider '{component_id}' has invalid lifetime: {self.lifetime}"
            )
        if not callable(self.create):
            raise ComponentRegistryError(
                f"component provider '{component_id}' create must be callable"
            )
        object.__setattr__(self, "id", component_id)


class ComponentScope:
    """Lazy component-instance scope owned by one composition node."""

    def __init__(self, registry: ComponentRegistry, scope_id: str) -> None:
        normalized_id = scope_id.strip()
        if not normalized_id:
            raise ComponentRegistryError("component scope id must not be empty")
        self.id = normalized_id
        self._registry = registry
        self._instances: dict[str, object] = {}
        self._resolving: list[str] = []

    def require[T](self, component_id: str, expected_type: type[T]) -> T:
        """Resolve and type-check one component in this scope."""
        provider = self._registry.require_provider(component_id)
        instances = (
            self._registry._runtime_instances if provider.lifetime == "runtime" else self._instances
        )
        if provider.id not in instances:
            self._create(provider, instances)
        component = instances[provider.id]
        if not isinstance(component, expected_type):
            raise ComponentRegistryError(
                f"component '{provider.id}' has type {type(component).__name__}, "
                f"expected {expected_type.__name__}"
            )
        return component

    def _create(
        self,
        provider: ComponentProvider,
        instances: dict[str, object],
    ) -> None:
        if provider.id in self._resolving:
            cycle_start = self._resolving.index(provider.id)
            cycle = (*self._resolving[cycle_start:], provider.id)
            raise ComponentRegistryError(
                f"component provider dependency cycle: {' -> '.join(cycle)}"
            )
        self._resolving.append(provider.id)
        try:
            instance = provider.create(self)
        finally:
            self._resolving.pop()
        instances[provider.id] = instance


class ComponentRegistry:
    """Registry of component providers with explicit instance lifetimes."""

    def __init__(self) -> None:
        self._providers: dict[str, ComponentProvider] = {}
        self._runtime_instances: dict[str, object] = {}
        self._root_scope = ComponentScope(self, "core.root")

    @property
    def root_scope(self) -> ComponentScope:
        """Return the stable scope used by direct, non-composition core callers."""
        return self._root_scope

    def register_provider(self, provider: ComponentProvider) -> None:
        if not isinstance(provider, ComponentProvider):
            raise ComponentRegistryError("provider must be a ComponentProvider")
        if provider.id in self._providers:
            raise ComponentRegistryError(f"component provider already registered: {provider.id}")
        self._providers[provider.id] = provider

    def require_provider(self, component_id: str) -> ComponentProvider:
        try:
            return self._providers[component_id]
        except KeyError as exc:
            raise ComponentRegistryError(f"component provider not found: {component_id}") from exc

    def create_scope(self, scope_id: str) -> ComponentScope:
        return ComponentScope(self, scope_id)

    def require[T](self, component_id: str, expected_type: type[T]) -> T:
        """Resolve a component for direct core use through the stable root scope."""
        return self._root_scope.require(component_id, expected_type)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    def providers(self) -> tuple[ComponentProvider, ...]:
        return tuple(self._providers[item] for item in sorted(self._providers))


def create_core_component_registry() -> ComponentRegistry:
    """Build the provider registry for the primitive core capabilities."""
    from .application import ApplicationComponent
    from .composition import CompositionComponent
    from .datamodel import DatamodelComponent
    from .element import ElementComponent
    from .module.component import ModuleComponent

    registry = ComponentRegistry()
    registry.register_provider(
        ComponentProvider(
            id="element",
            lifetime="composition",
            create=lambda scope: ElementComponent.with_core_types(),
        )
    )
    registry.register_provider(
        ComponentProvider(
            id="datamodel",
            lifetime="composition",
            create=lambda scope: DatamodelComponent(
                element=scope.require("element", ElementComponent)
            ),
        )
    )
    registry.register_provider(
        ComponentProvider(
            id="composition",
            lifetime="runtime",
            create=lambda scope: CompositionComponent(components=registry),
        )
    )
    registry.register_provider(
        ComponentProvider(
            id="application",
            lifetime="runtime",
            create=lambda scope: ApplicationComponent(
                compositions=scope.require("composition", CompositionComponent)
            ),
        )
    )
    registry.register_provider(
        ComponentProvider(
            id="module",
            lifetime="runtime",
            create=lambda scope: ModuleComponent(
                compositions=scope.require("composition", CompositionComponent),
                applications=scope.require("application", ApplicationComponent),
            ),
        )
    )
    return registry
