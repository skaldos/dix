from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Protocol, cast

from dix.core.composition import CompositionRuntimeContext


class StateApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class IpcApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Manage explicit, ephemeral Sway container groups without Sway commands."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
        state: StateApi,
        ipc: IpcApi,
    ) -> None:
        self.context = context
        self.config = config
        self.state = state
        self.ipc = ipc

    def create(self, group: str) -> None:
        name = _group_name(group)
        groups, active_group = self._snapshot()
        if name in groups:
            raise ValueError(f"Sway group already exists: {name}")
        groups[name] = []
        self._save(groups, active_group)

    def add(self, group: str) -> bool:
        name = _group_name(group)
        groups, active_group = self._snapshot()
        members = _existing_group(groups, name)
        con_id = self._focused_con_id()
        if con_id in members:
            return False
        members.append(con_id)
        self._save(groups, active_group)
        return True

    def remove(self, group: str) -> bool:
        name = _group_name(group)
        groups, active_group = self._snapshot()
        members = _existing_group(groups, name)
        con_id = self._focused_con_id()
        if con_id not in members:
            return False
        members.remove(con_id)
        self._save(groups, active_group)
        return True

    def show(self, group: str) -> list[int]:
        groups, _ = self._snapshot()
        return list(_existing_group(groups, _group_name(group)))

    def list(self) -> dict[str, list[int]]:
        groups, _ = self._snapshot()
        return {name: list(members) for name, members in groups.items()}

    def select(self, group: str) -> bool:
        name = _group_name(group)
        groups, active_group = self._snapshot()
        _existing_group(groups, name)
        return self._save(groups, name) if name != active_group else False

    def current(self) -> str:
        _, active_group = self._snapshot()
        return active_group

    def _snapshot(self) -> tuple[dict[str, list[int]], str]:
        value = self.state.require("get")()
        if not isinstance(value, Mapping):
            raise TypeError("Sway groups state must be a mapping")
        groups = value.get("groups", {})
        if not isinstance(groups, Mapping):
            raise TypeError("Sway groups state field 'groups' must be a mapping")
        result: dict[str, list[int]] = {}
        for group, members in groups.items():
            if not isinstance(group, str) or not group.strip():
                raise TypeError("Sway group names must be non-empty strings")
            if not isinstance(members, list):
                raise TypeError(f"Sway group '{group}' members must be a list")
            if any(type(member) is not int for member in members):
                raise TypeError(f"Sway group '{group}' members must be integer con_ids")
            if len(set(members)) != len(members):
                raise ValueError(f"Sway group '{group}' contains duplicate con_ids")
            result[group] = list(members)
        active_group = value.get("active_group", "")
        if not isinstance(active_group, str):
            raise TypeError("Sway groups state field 'active_group' must be a string")
        if active_group and active_group not in result:
            raise ValueError(f"active Sway group does not exist: {active_group}")
        return result, active_group

    def _save(self, groups: dict[str, list[int]], active_group: str) -> bool:
        changed = self.state.require("set")(
            {"groups": deepcopy(groups), "active_group": active_group}
        )
        if type(changed) is not bool:
            raise TypeError("ROBA state set must return a boolean")
        return changed

    def _focused_con_id(self) -> int:
        value = self.ipc.require("focused_con_id")()
        if type(value) is not int:
            raise TypeError("Sway IPC focused_con_id must return an integer")
        return value


def _existing_group(groups: Mapping[str, list[int]], name: str) -> list[int]:
    try:
        return groups[name]
    except KeyError as exc:
        raise ValueError(f"unknown Sway group: {name}") from exc


def _group_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Sway group name must be a non-empty string")
    return value.strip()
