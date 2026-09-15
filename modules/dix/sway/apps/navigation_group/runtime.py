from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from dix.core.application import ApplicationApi, ApplicationRuntimeContext


class IpcApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Filter repeated native Sway focus steps through the active group."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        basic: ApplicationApi,
        active_members: IpcApi,
        ipc: IpcApi,
    ) -> None:
        self.context = context
        self.config = config
        self.basic = basic
        self.active_members = active_members
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
        members = _integer_ids(
            self.active_members.require("get")(),
            "active Sway members",
        )
        if not members:
            result = self.basic.require(direction)()
            if not isinstance(result, dict):
                raise TypeError("basic Sway navigation must return a dictionary")
            return result
        origin_id = self._focused_con_id()
        live_ids = _integer_ids(self.ipc.require("live_con_ids")(), "live Sway con_ids")
        live = set(live_ids)
        stale_ids = [con_id for con_id in members if con_id not in live]
        allowed_ids = [con_id for con_id in members if con_id in live]
        visited_ids = [origin_id]
        visited = {origin_id}

        if not any(con_id != origin_id for con_id in allowed_ids):
            return _result(
                direction=direction,
                origin_id=origin_id,
                focused_id=origin_id,
                matched=False,
                restored=True,
                visited_ids=visited_ids,
                stale_ids=stale_ids,
            )

        current_id = origin_id
        matched = False
        limit = max(1, len(live_ids) + 1)
        move = self.basic.require(direction)
        for _ in range(limit):
            step = move()
            focused_id = _step_focus(step, direction, current_id)
            repeated = focused_id in visited
            if not repeated:
                visited.add(focused_id)
                visited_ids.append(focused_id)
            if focused_id != origin_id and focused_id in allowed_ids:
                current_id = focused_id
                matched = True
                break
            unchanged = focused_id == current_id
            current_id = focused_id
            if unchanged or repeated:
                break

        if matched:
            return _result(
                direction=direction,
                origin_id=origin_id,
                focused_id=current_id,
                matched=True,
                restored=False,
                visited_ids=visited_ids,
                stale_ids=stale_ids,
            )

        if current_id != origin_id:
            restored = self.ipc.require("focus_con_id")(origin_id)
            if restored is not None:
                raise TypeError("Sway IPC focus_con_id must return None")
            current_id = self._focused_con_id()
            if current_id != origin_id:
                raise RuntimeError(
                    f"Sway focus restore failed: expected {origin_id}, got {current_id}"
                )

        return _result(
            direction=direction,
            origin_id=origin_id,
            focused_id=current_id,
            matched=False,
            restored=current_id == origin_id,
            visited_ids=visited_ids,
            stale_ids=stale_ids,
        )

    def _focused_con_id(self) -> int:
        value = self.ipc.require("focused_con_id")()
        if type(value) is not int:
            raise TypeError("Sway IPC focused_con_id must return an integer")
        return value


def _integer_ids(value: object, label: str) -> list[int]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be a list")
    result: list[int] = []
    seen: set[int] = set()
    for item in value:
        if type(item) is not int:
            raise TypeError(f"{label} must contain integer con_ids")
        if item in seen:
            raise ValueError(f"{label} must not contain duplicate con_ids")
        seen.add(item)
        result.append(item)
    return result


def _step_focus(value: object, direction: str, expected_origin: int) -> int:
    if not isinstance(value, Mapping):
        raise TypeError("basic Sway navigation result must be a mapping")
    if set(value) != {"direction", "origin_id", "focused_id", "changed"}:
        raise TypeError("basic Sway navigation result has unexpected fields")
    if value["direction"] != direction:
        raise ValueError("basic Sway navigation returned the wrong direction")
    if type(value["origin_id"]) is not int or value["origin_id"] != expected_origin:
        raise ValueError("basic Sway navigation returned an unexpected origin_id")
    focused_id = value["focused_id"]
    if type(focused_id) is not int:
        raise TypeError("basic Sway navigation focused_id must be an integer")
    changed = value["changed"]
    if type(changed) is not bool or changed != (focused_id != expected_origin):
        raise ValueError("basic Sway navigation returned an invalid changed value")
    return focused_id


def _result(
    *,
    direction: str,
    origin_id: int,
    focused_id: int,
    matched: bool,
    restored: bool,
    visited_ids: list[int],
    stale_ids: list[int],
) -> dict[str, object]:
    return {
        "direction": direction,
        "origin_id": origin_id,
        "focused_id": focused_id,
        "matched": matched,
        "restored": restored,
        "visited_ids": list(visited_ids),
        "stale_ids": list(stale_ids),
    }
