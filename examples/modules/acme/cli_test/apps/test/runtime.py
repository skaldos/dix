from __future__ import annotations

import asyncio
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

    def hello(self, *, name: str) -> str:
        """Greet one named recipient."""
        return f"Hello {name}"

    async def hello_world(self) -> str:
        """Return an asynchronous world greeting."""
        await asyncio.sleep(0)
        return "Hello World"

    def status(self) -> str:
        """Return the test application status."""
        return "test:ready"
