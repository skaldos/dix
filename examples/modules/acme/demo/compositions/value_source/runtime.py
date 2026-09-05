from __future__ import annotations

from collections.abc import Mapping

from dix.core.composition import CompositionRuntimeContext


class Runtime:
    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
    ) -> None:
        self.context = context
        self.config = config
        self.initialized = False

    def init(self) -> None:
        self.initialized = True

    def cleanup(self) -> None:
        self.initialized = False

    def read(self, value: str) -> str:
        """Return a deterministic namespaced value."""
        if not self.initialized:
            raise RuntimeError("value_source is not initialized")
        return f"value:{value}"
