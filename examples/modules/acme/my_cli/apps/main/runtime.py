from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from dix.core.application import ApplicationApi, ApplicationRuntimeContext


class CliApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Small application-owned glue for one concrete CLI assembly."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        cli: CliApi,
        base: ApplicationApi,
        test: ApplicationApi,
    ) -> None:
        self.context = context
        self.config = config
        self.cli = cli
        self.targets = {"base": base, "test": test}

    def main(self, argv: Sequence[str]) -> int:
        """Run the explicitly composed multi-application CLI."""
        invoke = self.cli.require("invoke")
        result = invoke(name="my_cli", targets=self.targets, argv=argv)
        if type(result) is not int:
            raise TypeError("Typer invoke must return an integer exit code")
        return result
