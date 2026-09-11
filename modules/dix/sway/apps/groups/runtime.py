from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from dix.core.application import ApplicationRuntimeContext


class GroupsApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Expose the explicit Sway groups composition as an application."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        groups: GroupsApi,
    ) -> None:
        self.context = context
        self.config = config
        self.groups = groups

    def create(self, group: str) -> None:
        return self.groups.require("create")(group)

    def add(self, group: str) -> bool:
        return self.groups.require("add")(group)

    def remove(self, group: str) -> bool:
        return self.groups.require("remove")(group)

    def show(self, group: str) -> list[int]:
        return self.groups.require("show")(group)

    def list(self) -> dict[str, list[int]]:
        return self.groups.require("list")()
