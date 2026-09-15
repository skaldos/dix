from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import json
import os
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
    def __init__(self, *, error: Exception | None = None) -> None:
        self.writes: list[dict[str, object]] = []
        self.error = error

    def api(self) -> _Api:
        return _Api({"get": self.get, "set": self.set})

    def get(self) -> object:
        raise AssertionError("group composition must not read ROBA state")

    def set(self, value: dict[str, object]) -> bool:
        if self.error is not None:
            raise self.error
        self.writes.append(deepcopy(value))
        return True


class _Ipc:
    def __init__(self, focused: int = 42) -> None:
        self.focused = focused

    def api(self) -> _Api:
        return _Api({"focused_con_id": lambda: self.focused})


def _runtime(tmp_path: Path, state: _State | None = None, ipc: _Ipc | None = None):
    state = state or _State()
    ipc = ipc or _Ipc()
    context = CompositionRuntimeContext(
        instance_id="groups", composition_id="dix/sway/groups", module_id="dix/sway",
        module_root=Path("."), composition_root=Path("."), config_base_dir=Path("."),
        owner_scope_id="test",
    )
    path = tmp_path / "groups.json"
    return runtime_module.Runtime(context=context, config={"state_file": str(path)}, state=state.api(), ipc=ipc.api()), state, ipc, path


def test_create_add_remove_show_and_list_use_private_state(tmp_path: Path) -> None:
    runtime, state, ipc, path = _runtime(tmp_path)
    assert runtime.create("work") is None
    assert runtime.add("work") is True
    assert runtime.add("work") is False
    assert runtime.show("work") == [42]
    assert runtime.list() == {"work": [42]}
    assert runtime.remove("work") is True
    assert runtime.remove("work") is False
    assert runtime.list() == {"work": []}
    assert ipc.focused == 42
    assert state.writes == [{"groups": ["work"], "active_group": ""}]
    assert json.loads(path.read_text()) == {"groups": {"work": []}, "active_group": ""}
    assert path.read_bytes().endswith(b"\n")


def test_missing_is_empty_but_existing_invalid_files_fail(tmp_path: Path) -> None:
    runtime, _, _, path = _runtime(tmp_path)
    assert runtime.list() == {}
    for raw in (b"", b"{", b"{}\n", b'{"groups":{},"active_group":"missing"}\n'):
        path.write_bytes(raw)
        with pytest.raises((TypeError, ValueError)):
            runtime.list()


def test_private_validation_rejects_invalid_members(tmp_path: Path) -> None:
    runtime, _, _, path = _runtime(tmp_path)
    for value in (
        {"groups": {"work": "not-a-list"}, "active_group": ""},
        {"groups": {"work": [True]}, "active_group": ""},
        {"groups": {"work": [0]}, "active_group": ""},
        {"groups": {"work": [1, 1]}, "active_group": ""},
        {"groups": {" work ": []}, "active_group": ""},
    ):
        path.write_text(json.dumps(value) + "\n")
        with pytest.raises((TypeError, ValueError)):
            runtime.list()


def test_names_unknown_groups_and_detached_results(tmp_path: Path) -> None:
    runtime, _, _, _ = _runtime(tmp_path)
    with pytest.raises(ValueError, match="non-empty"):
        runtime.create(" ")
    runtime.create(" one ")
    runtime.create("two")
    with pytest.raises(ValueError, match="already exists"):
        runtime.create("one")
    with pytest.raises(ValueError, match="unknown"):
        runtime.show("missing")
    runtime.add("one")
    runtime.add("two")
    result = runtime.list()
    result["one"].append(99)
    assert runtime.list() == {"one": [42], "two": [42]}


def test_roba_call_matrix_and_selection(tmp_path: Path) -> None:
    runtime, state, _, _ = _runtime(tmp_path)
    assert runtime.current() == ""
    runtime.create("work")
    assert runtime.select("work") is True
    assert runtime.select("work") is False
    runtime.add("work")
    runtime.remove("work")
    runtime.show("work")
    runtime.list()
    runtime.current()
    assert state.writes == [
        {"groups": ["work"], "active_group": ""},
        {"groups": ["work"], "active_group": "work"},
    ]


def test_private_write_precedes_visible_roba_failure(tmp_path: Path) -> None:
    runtime, _, _, path = _runtime(tmp_path, _State(error=RuntimeError("coordination failed")))
    with pytest.raises(RuntimeError, match="coordination failed"):
        runtime.create("work")
    assert json.loads(path.read_text()) == {"groups": {"work": []}, "active_group": ""}


def test_writer_uses_same_directory_atomic_replace(tmp_path: Path, monkeypatch) -> None:
    runtime, _, _, path = _runtime(tmp_path)
    calls: list[tuple[Path, Path]] = []
    original = os.replace
    def replace(source, target):
        calls.append((Path(source), Path(target)))
        original(source, target)
    monkeypatch.setattr(os, "replace", replace)
    runtime.create("work")
    assert calls and calls[0][0].parent == path.parent and calls[0][1] == path


def test_explicit_path_is_required(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DIX_SWAY_GROUP_STATE_FILE", raising=False)
    context = CompositionRuntimeContext(
        instance_id="groups", composition_id="dix/sway/groups", module_id="dix/sway",
        module_root=tmp_path, composition_root=tmp_path, config_base_dir=tmp_path,
        owner_scope_id="test",
    )
    with pytest.raises(ValueError, match="path must be set"):
        runtime_module.Runtime(context=context, config={}, state=_State().api(), ipc=_Ipc().api())
