from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from dix.core.application import ApplicationRuntimeContext


class ApplicationApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Glue between the generic application runner and automatic Typer projection."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        cli: ApplicationApi,
        runner: ApplicationApi,
    ) -> None:
        self.context = context
        self.config = config
        self.cli = cli
        self.runner = runner

    def describe(self, application_id: str) -> Mapping[str, object]:
        descriptor = self.runner.require("describe_application")(application_id)
        return self.cli.require("describe_application")(descriptor=descriptor)

    def run(
        self,
        application_id: str,
        application_config: Mapping[str, object],
        argv: Sequence[str],
    ) -> int:
        descriptor = self.runner.require("describe_application")(application_id)

        def invoke(
            function_id: str,
            args: Sequence[object],
            kwargs: Mapping[str, object],
        ) -> object:
            return asyncio.run(
                self.runner.require("execute")(
                    application_id,
                    function_id,
                    args,
                    kwargs,
                    application_config,
                )
            )

        return self.cli.require("invoke_application")(
            descriptor=descriptor,
            invoke=invoke,
            argv=argv,
        )
