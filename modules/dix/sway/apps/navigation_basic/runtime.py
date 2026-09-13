from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from dix.core.application import ApplicationRuntimeContext


class IpcApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Expose one native Sway focus step behind four directional functions."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        ipc: IpcApi,
    ) -> None:
        self.context = context
        self.config = config
        self.ipc = ipc

    def left(self) -> dict[str, object]:
        return self._move("left")

    def right(self) -> dict[str, object]:
        return self._move("right")

    def up(self) -> dict[str, object]:
        return self._move("up")

    def down(self) -> dict[str, object]:
        return self._move("down")

    def _move(self, direction: str) -> dict[str, object]:
        origin_id = self._focused_con_id()
        command_result = self.ipc.require("focus_direction")(direction)
        if command_result is not None:
            raise TypeError("Sway IPC focus_direction must return None")
        focused_id = self._focused_con_id()
        return {
            "direction": direction,
            "origin_id": origin_id,
            "focused_id": focused_id,
            "changed": focused_id != origin_id,
        }

    def _focused_con_id(self) -> int:
        value = self.ipc.require("focused_con_id")()
        if type(value) is not int:
            raise TypeError("Sway IPC focused_con_id must return an integer")
        return value
