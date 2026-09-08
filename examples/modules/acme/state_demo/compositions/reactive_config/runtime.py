from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from dix.core.composition import CompositionRuntimeContext


class StateApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Own reaction policy without adding it to dix/state/local."""

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
        self._reaction_count = 0

    def get(self) -> dict[str, object]:
        """Return the complete reactive state."""
        return self.state.require("get")()

    def set(self, values: Mapping[str, object]) -> bool:
        """Replace the state and apply owner-local reaction policy."""
        changed = self.state.require("set")(values)
        if changed:
            self._config_changed()
        return changed

    def reaction_count(self) -> int:
        """Return the number of owner-local reactions."""
        return self._reaction_count

    def _config_changed(self) -> None:
        self._reaction_count += 1
