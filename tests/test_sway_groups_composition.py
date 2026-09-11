from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import dix_sway_groups_runtime_test_import as runtime_module
from dix.core.composition import CompositionRuntimeContext


class _Api:
    def __init__(self, functions: dict[str, Callable[..., object]]) -> None:
        self.functions = functions

    def require(self, function_id: str) -> Callable[..., object]:
        return self.functions[function_id]


class _State:
    def __init__(self, value: dict[str, object] | None = None) -> None:
        self.value = value or {"groups": {}}
        self.writes: list[dict[str, object]] = []

    def api(self) -> _Api:
        return _Api({"get": self.get, "set": self.set})

    def get(self) -> dict[str, object]:
        return {"groups": {name: list(members) for name, members in self.value["groups"].items()}}

    def set(self, value: dict[str, object]) -> bool:
        self.writes.append(value)
        self.value = value
        return True


class _Ipc:
    def __init__(self, focused: int = 42) -> None:
        self.focused = focused

    def api(self) -> _Api:
        return _Api({"focused_con_id": lambda: self.focused})


def _runtime(state: _State | None = None, ipc: _Ipc | None = None):
    state = state or _State()
    ipc = ipc or _Ipc()
    context = CompositionRuntimeContext(
        instance_id="groups",
        composition_id="dix/sway/groups",
        module_id="dix/sway",
        module_root=Path("."),
        composition_root=Path("."),
        config_base_dir=Path("."),
        owner_scope_id="test",
    )
    return runtime_module.Runtime(
        context=context,
        config={},
        state=state.api(),
        ipc=ipc.api(),
    ), state, ipc


def test_create_add_remove_show_and_list_use_only_explicit_operations() -> None:
    runtime, state, ipc = _runtime()

    assert runtime.create("work") is None
    assert runtime.add("work") is True
    assert runtime.add("work") is False
    assert runtime.show("work") == [42]
    assert runtime.list() == {"work": [42]}
    assert runtime.remove("work") is True
    assert runtime.remove("work") is False
    assert runtime.list() == {"work": []}
    assert ipc.focused == 42
    assert len(state.writes) == 3


def test_group_names_and_unknown_groups_are_explicit_errors() -> None:
    runtime, _, _ = _runtime()

    with pytest.raises(ValueError, match="non-empty"):
        runtime.create(" ")
    runtime.create("work")
    with pytest.raises(ValueError, match="already exists"):
        runtime.create("work")
    with pytest.raises(ValueError, match="unknown"):
        runtime.show("missing")
    with pytest.raises(ValueError, match="unknown"):
        runtime.add("missing")


def test_state_validation_rejects_invalid_inner_groups_and_bool_ids() -> None:
    for value in (
        {"groups": {"work": "not-a-list"}},
        {"groups": {"work": [True]}},
        {"groups": {"work": [1, 1]}},
    ):
        runtime, _, _ = _runtime(_State(value))
        with pytest.raises((TypeError, ValueError)):
            runtime.list()


def test_same_container_can_belong_to_multiple_groups_and_results_are_detached() -> None:
    runtime, state, _ = _runtime()
    runtime.create("one")
    runtime.create("two")
    assert runtime.add("one") is True
    assert runtime.add("two") is True

    result = runtime.list()
    result["one"].append(99)
    assert runtime.list() == {"one": [42], "two": [42]}
    assert state.value == {"groups": {"one": [42], "two": [42]}}


def test_add_and_remove_read_focus_only_when_group_exists() -> None:
    runtime, _, ipc = _runtime()
    with pytest.raises(ValueError):
        runtime.add("missing")
    assert ipc.focused == 42
