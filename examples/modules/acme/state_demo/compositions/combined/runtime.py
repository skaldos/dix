from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from dix.core.composition import CompositionRuntimeContext


class CompositionApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Combine only the functions exposed by two direct owner dependencies."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
        base: CompositionApi,
        reactive: CompositionApi,
    ) -> None:
        self.context = context
        self.config = config
        self.base = base
        self.reactive = reactive

    def get_base(self) -> dict[str, object]:
        return self.base.require("get")()

    def set_base(self, values: Mapping[str, object]) -> bool:
        return self.base.require("set")(values)

    def get_reactive(self) -> dict[str, object]:
        return self.reactive.require("get")()

    def set_reactive(self, values: Mapping[str, object]) -> bool:
        return self.reactive.require("set")(values)

    def reaction_count(self) -> int:
        return self.reactive.require("reaction_count")()
