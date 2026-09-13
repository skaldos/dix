from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from dix.core.application import ApplicationApi, ApplicationRuntimeContext


class StateApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Route four directions through one of two explicitly composed applications."""

    _TARGETS = {"basic": "basic", "group": "group"}

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        state: StateApi,
        basic: ApplicationApi,
        group: ApplicationApi,
    ) -> None:
        self.context = context
        self.config = config
        self.state = state
        self.basic = basic
        self.group = group

    def select(self, node_selector: str) -> bool:
        selector = _selector(node_selector)
        changed = self.state.require("set")({"node_selector": selector})
        if type(changed) is not bool:
            raise TypeError("ROBA state set must return a boolean")
        return changed

    def current(self) -> str:
        return self._selector()

    def left(self) -> dict[str, object]:
        return self._move("left")

    def right(self) -> dict[str, object]:
        return self._move("right")

    def up(self) -> dict[str, object]:
        return self._move("up")

    def down(self) -> dict[str, object]:
        return self._move("down")

    def _move(self, direction: str) -> dict[str, object]:
        selector = self._selector()
        target = self.basic if self._TARGETS[selector] == "basic" else self.group
        result = target.require(direction)()
        if not isinstance(result, Mapping):
            raise TypeError("selected Sway navigation must return a mapping")
        return dict(result)

    def _selector(self) -> str:
        value = self.state.require("get")()
        if not isinstance(value, Mapping):
            raise TypeError("Sway navigation state must be a mapping")
        return _selector(value.get("node_selector"))


def _selector(value: object) -> str:
    if not isinstance(value, str) or value not in {"basic", "group"}:
        raise ValueError(f"unknown Sway node selector: {value!r}")
    return value
