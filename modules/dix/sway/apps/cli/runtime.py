from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from dix.core.application import ApplicationApi, ApplicationRuntimeContext


class TyperApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Project the Sway runtime and groups applications through Typer."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        typer: TyperApi,
        groups: ApplicationApi,
        runtime: ApplicationApi,
    ) -> None:
        self.context = context
        self.config = config
        self.typer = typer
        self.groups = groups
        self.runtime = runtime

    def main(self, argv: Sequence[str]) -> int:
        """Run the explicit DIX Sway runtime and groups CLI."""
        result = self.typer.require("invoke")(
            name="dix-sway",
            targets={"group": self.groups, "runtime": self.runtime},
            argv=argv,
        )
        if type(result) is not int:
            raise TypeError("Typer invoke must return an integer exit code")
        return result
