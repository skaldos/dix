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

    def render(self, *, value: str, count: int = 1, upper: bool = False) -> str:
        """Render one value repeatedly."""
        rendered = value.upper() if upper else value
        return "\n".join(rendered for _ in range(count))

    def status(self) -> str:
        """Return the base application status."""
        return "base:ready"

    def hidden_helper(self) -> str:
        """Remain invisible because the application does not expose this method."""
        return "hidden"
