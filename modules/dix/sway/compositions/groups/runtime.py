from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from typing import Protocol

from dix.core.composition import CompositionRuntimeContext


class StateApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class IpcApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Own Sway group membership privately and publish only coordination."""

    def __init__(self, *, context: CompositionRuntimeContext, config: Mapping[str, object], state: StateApi, ipc: IpcApi) -> None:
        self.context = context
        self.config = config
        self.state = state
        self.ipc = ipc
        configured = config.get("state_file")
        if configured is None:
            configured = os.environ.get("DIX_SWAY_GROUP_STATE_FILE")
        if not isinstance(configured, str) or not configured:
            raise ValueError("Sway group state path must be set through state_file or DIX_SWAY_GROUP_STATE_FILE")
        self.state_file = Path(configured)

    def create(self, group: str) -> None:
        name = _group_name(group)
        groups, active_group = self._snapshot()
        if name in groups:
            raise ValueError(f"Sway group already exists: {name}")
        groups[name] = []
        self._write_private(groups, active_group)
        self._publish_coordination(groups, active_group)

    def add(self, group: str) -> bool:
        name = _group_name(group)
        groups, active_group = self._snapshot()
        members = _existing_group(groups, name)
        con_id = self._focused_con_id()
        if con_id in members:
            return False
        members.append(con_id)
        self._write_private(groups, active_group)
        return True

    def remove(self, group: str) -> bool:
        name = _group_name(group)
        groups, active_group = self._snapshot()
        members = _existing_group(groups, name)
        con_id = self._focused_con_id()
        if con_id not in members:
            return False
        members.remove(con_id)
        self._write_private(groups, active_group)
        return True

    def show(self, group: str) -> list[int]:
        groups, _ = self._snapshot()
        return list(_existing_group(groups, _group_name(group)))

    def list(self) -> dict[str, list[int]]:
        groups, _ = self._snapshot()
        return deepcopy(groups)

    def select(self, group: str) -> bool:
        name = _group_name(group)
        groups, active_group = self._snapshot()
        _existing_group(groups, name)
        if name == active_group:
            return False
        self._write_private(groups, name)
        self._publish_coordination(groups, name)
        return True

    def current(self) -> str:
        _, active_group = self._snapshot()
        return active_group

    def _snapshot(self) -> tuple[dict[str, list[int]], str]:
        if not self.state_file.exists():
            return {}, ""
        try:
            value = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read Sway group state: {exc}") from exc
        return _validate_private_state(value)

    def _write_private(self, groups: dict[str, list[int]], active_group: str) -> None:
        checked_groups, checked_active = _validate_private_state({"groups": groups, "active_group": active_group})
        payload = json.dumps(
            {"groups": checked_groups, "active_group": checked_active}, ensure_ascii=False,
            sort_keys=True, separators=(",", ":"),
        ) + "\n"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.state_file.parent, prefix=f".{self.state_file.name}.", delete=False) as handle:
                temporary = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_file)
            temporary = None
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    def _publish_coordination(self, groups: Mapping[str, list[int]], active_group: str) -> None:
        changed = self.state.require("set")({"groups": list(groups), "active_group": active_group})
        if type(changed) is not bool:
            raise TypeError("ROBA state set must return a boolean")

    def _focused_con_id(self) -> int:
        value = self.ipc.require("focused_con_id")()
        if type(value) is not int or value <= 0:
            raise TypeError("Sway IPC focused_con_id must return a positive integer")
        return value


def _validate_private_state(value: object) -> tuple[dict[str, list[int]], str]:
    if not isinstance(value, Mapping) or set(value) != {"groups", "active_group"}:
        raise TypeError("Sway group state must contain exactly groups and active_group")
    groups = value["groups"]
    if not isinstance(groups, Mapping):
        raise TypeError("Sway group state field 'groups' must be a mapping")
    result: dict[str, list[int]] = {}
    for raw_group, members in groups.items():
        group = _group_name(raw_group)
        if group != raw_group:
            raise ValueError("stored Sway group names must already be normalized")
        if not isinstance(members, list):
            raise TypeError(f"Sway group '{group}' members must be a list")
        if any(type(member) is not int or member <= 0 for member in members):
            raise TypeError(f"Sway group '{group}' members must be positive integer con_ids")
        if len(set(members)) != len(members):
            raise ValueError(f"Sway group '{group}' contains duplicate con_ids")
        result[group] = list(members)
    active_group = value["active_group"]
    if not isinstance(active_group, str):
        raise TypeError("Sway group state field 'active_group' must be a string")
    if active_group and active_group not in result:
        raise ValueError(f"active Sway group does not exist: {active_group}")
    return result, active_group


def _existing_group(groups: Mapping[str, list[int]], name: str) -> list[int]:
    try:
        return groups[name]
    except KeyError as exc:
        raise ValueError(f"unknown Sway group: {name}") from exc


def _group_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Sway group name must be a non-empty string")
    return value.strip()
