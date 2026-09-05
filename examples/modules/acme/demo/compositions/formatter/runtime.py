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

    def format(self, value: str) -> str:
        """Wrap one value in a deterministic representation."""
        if not self.initialized:
            raise RuntimeError("formatter is not initialized")
        return f"formatted<{value}>"
