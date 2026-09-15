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

    def decorate(self, value: str) -> str:
        """Decorate one value in the external fixture."""
        return f"external<{value}>"
