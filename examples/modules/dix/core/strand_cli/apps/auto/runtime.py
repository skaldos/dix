from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from dix.core.application import ApplicationRuntimeContext


class DependencyApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Glue between an application knot and the generic strand Typer projection."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        cli: DependencyApi,
        runner: DependencyApi,
    ) -> None:
        self.context = context
        self.config = config
        self.cli = cli
        self.runner = runner

    def describe(self, application_id: str) -> Mapping[str, object]:
        descriptors = self.runner.require("bind_application")(application_id, {})
        return self.cli.require("describe_strands")(
            name=application_id,
            descriptors=descriptors,
        )

    def run(
        self,
        application_id: str,
        application_config: Mapping[str, object],
        argv: Sequence[str],
    ) -> int:
        descriptors = self.runner.require("bind_application")(
            application_id,
            application_config,
        )

        def invoke(strand_id: str, value: Mapping[str, object]) -> object:
            return asyncio.run(self.runner.require("call")(strand_id, value))

        return self.cli.require("invoke_strands")(
            name=application_id,
            descriptors=descriptors,
            invoke=invoke,
            argv=argv,
        )
