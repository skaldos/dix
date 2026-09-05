from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from dix.core.application import ApplicationRuntimeContext


class BaseApi(Protocol):
    def render(self, value: str) -> str: ...


class Runtime:
    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        base: BaseApi,
    ) -> None:
        self.context = context
        self.config = config
        self.base = base

    def render(self, value: str) -> str:
        """Delegate to the base application through a real local wrapper."""
        return self.base.render(value)

    def describe(self, value: str) -> str:
        """Add child-local behavior to the recursive result."""
        return f"child[{self.render(value)}]"

    def hidden(self) -> str:
        return "not declared"
