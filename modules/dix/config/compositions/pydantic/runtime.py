from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from dix.core.composition import CompositionRuntimeContext


class Runtime:
    """Resolve owner-provided declarative specifications into Pydantic model types."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
    ) -> None:
        self.context = context
        self.config = config

    def resolve(self, spec: Mapping[str, object]) -> type[BaseModel]:
        """Resolve a declarative config model specification into a Pydantic model type."""
        raise NotImplementedError("declarative config model resolution is not implemented")
