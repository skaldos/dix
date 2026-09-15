from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from dix.core.application import ApplicationRuntimeContext


class PrefixApi(Protocol):
    def decorate(self, value: str) -> str: ...


class Runtime:
    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        prefix: PrefixApi,
    ) -> None:
        self.context = context
        self.config = config
        self.prefix = prefix

    def run(self, value: str) -> str:
        """Call one explicitly supplied external composition."""
        return f"consumer[{self.prefix.decorate(value)}]"
