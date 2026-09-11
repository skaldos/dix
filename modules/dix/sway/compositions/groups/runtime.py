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
        groups = self._groups()
        if name in groups:
            raise ValueError(f"Sway group already exists: {name}")
        groups[name] = []
        self._save(groups)

    def add(self, group: str) -> bool:
        name = _group_name(group)
        groups = self._groups()
        members = _existing_group(groups, name)
        con_id = self._focused_con_id()
        if con_id in members:
            return False
        members.append(con_id)
        self._save(groups)
        return True

    def remove(self, group: str) -> bool:
        name = _group_name(group)
        groups = self._groups()
        members = _existing_group(groups, name)
        con_id = self._focused_con_id()
        if con_id not in members:
            return False
        members.remove(con_id)
        self._save(groups)
        return True

    def show(self, group: str) -> list[int]:
        return list(_existing_group(self._groups(), _group_name(group)))

    def list(self) -> dict[str, list[int]]:
        return {name: list(members) for name, members in self._groups().items()}

    def _groups(self) -> dict[str, list[int]]:
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
        return result

    def _save(self, groups: dict[str, list[int]]) -> None:
        changed = self.state.require("set")({"groups": deepcopy(groups)})
        if type(changed) is not bool:
            raise TypeError("ROBA state set must return a boolean")

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
