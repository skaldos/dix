from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from dix.core.composition import CompositionRuntimeContext


class StateApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Transparently expose one local state through the normal dependency export."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
        state: StateApi,
    ) -> None:
        self.context = context
        self.config = config
        self.state = state

    def get(self) -> dict[str, object]:
        """Return the complete base state."""
        return self.state.require("get")()

    def set(self, values: Mapping[str, object]) -> bool:
        """Replace the complete base state."""
        return self.state.require("set")(values)
