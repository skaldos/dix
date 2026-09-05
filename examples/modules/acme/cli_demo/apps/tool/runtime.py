from __future__ import annotations

from collections.abc import Mapping

from dix.core.application import ApplicationRuntimeContext


class Runtime:
    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
    ) -> None:
        self.context = context
        self.config = config

    def render(self, *, value: str, count: int, upper: bool) -> str:
        """Render one value repeatedly."""
        rendered = value.upper() if upper else value
        return "\n".join(rendered for _ in range(count))
