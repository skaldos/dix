from __future__ import annotations

from typing import Any, Mapping

from .base import (
    BoundComposition,
    CompositionContext,
    CompositionError,
    CompositionFactory,
    CompositionNotFound,
)


class CompositionRegistry:
    """Explicit allowlist of trusted, in-process composition factories."""

    def __init__(self) -> None:
        self._factories: dict[str, CompositionFactory] = {}

    def register(self, factory: CompositionFactory) -> None:
        raw_composition_id = getattr(factory, "composition_id", None)
        if not isinstance(raw_composition_id, str):
            raise CompositionError("composition factory must define a string composition_id")
        composition_id = raw_composition_id.strip()
        if not composition_id:
            raise CompositionError("composition_id must not be empty")
        if composition_id in self._factories:
            raise CompositionError(f"composition already registered: {composition_id}")
        self._factories[composition_id] = factory

    def require(self, composition_id: str) -> CompositionFactory:
        try:
            return self._factories[composition_id]
        except KeyError as exc:
            raise CompositionNotFound(f"composition not found: {composition_id}") from exc

    def bind(
        self,
        composition_id: str,
        context: CompositionContext,
        config: Mapping[str, Any],
    ) -> BoundComposition:
        return self.require(composition_id).bind(context, config)

    def ids(self) -> tuple[str, ...]:
        return tuple(self._factories)
