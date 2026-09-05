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

    def read(self, value: str) -> str:
        """Return a deterministic namespaced value."""
        return f"value:{value}"
