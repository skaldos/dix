from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from dix.core.application import ApplicationRuntimeContext


class FormatterApi(Protocol):
    def format(self, value: str) -> str: ...


class ValueSourceApi(Protocol):
    def read(self, value: str) -> str: ...


class Runtime:
    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        formatter: FormatterApi,
        source: ValueSourceApi,
    ) -> None:
        self.context = context
        self.config = config
        self.formatter = formatter
        self.source = source
        self.started = False

    def start(self) -> None:
        self.formatter.format(self.source.read("startup"))
        self.started = True

    def stop(self) -> None:
        self.started = False

    def render(self, value: str) -> str:
        """Read and format one value through both compositions."""
        if not self.started:
            raise RuntimeError("base application is not active")
        return self.formatter.format(self.source.read(value))

    def hidden(self) -> str:
        return "not declared"
