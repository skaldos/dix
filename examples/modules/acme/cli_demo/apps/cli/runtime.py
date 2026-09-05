from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from dix.core.application import ApplicationFunctionDescriptor, ApplicationRuntimeContext


class CliApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class ToolApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...

    def describe(self, function_id: str) -> ApplicationFunctionDescriptor: ...


class Runtime:
    """Small explicit glue between one CLI adapter and one allowed target."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        cli: CliApi,
        tool: ToolApi,
    ) -> None:
        self.context = context
        self.config = config
        self.cli = cli
        self.tool = tool

    def describe(self) -> Mapping[str, object]:
        """Describe the normalized demo CLI contract."""
        return self.cli.require("describe")(
            spec_path=self._spec_path,
            targets=self._targets,
        )

    def run(self, argv: Sequence[str]) -> int:
        """Run the demo CLI with explicit arguments."""
        return self.cli.require("invoke")(
            spec_path=self._spec_path,
            targets=self._targets,
            argv=argv,
        )

    @property
    def _spec_path(self) -> Path:
        return self.context.application_root / "cli.toml"

    @property
    def _targets(self) -> Mapping[str, Mapping[str, object]]:
        return {
            "tool.render": {
                "function": self.tool.require("render"),
                "descriptor": self.tool.describe("render"),
            }
        }
