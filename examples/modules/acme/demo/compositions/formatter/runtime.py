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

    def format(self, value: str) -> str:
        """Wrap one value in a deterministic representation."""
        return f"formatted<{value}>"
