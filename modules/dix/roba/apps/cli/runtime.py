from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from dix.core.application import ApplicationApi, ApplicationRuntimeContext


class TyperApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Own one small scriptable Typer projection for the ROBA daemon application."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        typer: TyperApi,
        daemon: ApplicationApi,
        control: ApplicationApi,
    ) -> None:
        self.context = context
        self.config = config
        self.typer = typer
        self.daemon = daemon
        self.control = control

    def main(self, argv: Sequence[str]) -> int:
        """Run the explicit DIX ROBA daemon CLI."""
        result = self.typer.require("invoke")(
            name="dix-roba",
            targets={"daemon": self.daemon, "control": self.control},
            argv=argv,
        )
        if type(result) is not int:
            raise TypeError("Typer invoke must return an integer exit code")
        return result
