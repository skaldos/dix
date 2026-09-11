from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from dix.core.application import ApplicationApi, ApplicationRuntimeContext


class TyperApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Project the Sway groups application through the shared Typer adapter."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        typer: TyperApi,
        groups: ApplicationApi,
    ) -> None:
        self.context = context
        self.config = config
        self.typer = typer
        self.groups = groups

    def main(self, argv: Sequence[str]) -> int:
        """Run the explicit DIX Sway groups CLI."""
        result = self.typer.require("invoke")(
            name="dix-sway",
            targets={"group": self.groups},
            argv=argv,
        )
        if type(result) is not int:
            raise TypeError("Typer invoke must return an integer exit code")
        return result
