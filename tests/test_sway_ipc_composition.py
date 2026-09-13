from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import dix_sway_ipc_runtime_test_import as runtime_module
from dix.core.composition import CompositionRuntimeContext


def _runtime() -> runtime_module.Runtime:
    context = CompositionRuntimeContext(
        instance_id="ipc",
        composition_id="dix/sway/ipc",
        module_id="dix/sway",
        module_root=Path("."),
        composition_root=Path("."),
        config_base_dir=Path("."),
        owner_scope_id="test",
    )
    return runtime_module.Runtime(context=context, config={})


def test_focused_con_id_exposes_only_the_integer_id(monkeypatch: pytest.MonkeyPatch) -> None:
    class Connection:
        def get_tree(self) -> object:
            return SimpleNamespace(find_focused=lambda: SimpleNamespace(id=817263))

    monkeypatch.setattr(runtime_module.i3ipc, "Connection", Connection)
    result = _runtime().focused_con_id()

    assert result == 817263
    assert type(result) is int


@pytest.mark.parametrize(
    "focused",
    [None, SimpleNamespace(id=True), SimpleNamespace(id="817263")],
)
def test_missing_or_invalid_focus_fails_at_the_adapter_boundary(
    monkeypatch: pytest.MonkeyPatch,
    focused: object,
) -> None:
    class Connection:
        def get_tree(self) -> object:
            return SimpleNamespace(find_focused=lambda: focused)

    monkeypatch.setattr(runtime_module.i3ipc, "Connection", Connection)
    with pytest.raises(runtime_module.SwayIpcError):
        _runtime().focused_con_id()


def test_connection_errors_are_visible_as_sway_ipc_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class Connection:
        def __init__(self) -> None:
            raise OSError("socket unavailable")

    monkeypatch.setattr(runtime_module.i3ipc, "Connection", Connection)
    with pytest.raises(runtime_module.SwayIpcError, match="socket unavailable"):
        _runtime().focused_con_id()


def test_no_i3ipc_object_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    class Connection:
        def get_tree(self) -> object:
            return SimpleNamespace(find_focused=lambda: SimpleNamespace(id=1))

    monkeypatch.setattr(runtime_module.i3ipc, "Connection", Connection)
    assert not isinstance(_runtime().focused_con_id(), runtime_module.i3ipc.Connection)


@pytest.mark.parametrize("direction", ["left", "right", "up", "down"])
def test_focus_direction_sends_exactly_one_native_command(
    monkeypatch: pytest.MonkeyPatch,
    direction: str,
) -> None:
    commands: list[str] = []

    class Connection:
        def command(self, command: str) -> list[object]:
            commands.append(command)
            return [SimpleNamespace(success=True)]

    monkeypatch.setattr(runtime_module.i3ipc, "Connection", Connection)
    assert _runtime().focus_direction(direction) is None
    assert commands == [f"focus {direction}"]


@pytest.mark.parametrize("direction", ["next", "prev", "LEFT", "", None, 1])
def test_focus_direction_rejects_every_other_value_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
    direction: object,
) -> None:
    def connection() -> object:
        raise AssertionError("invalid direction must not connect")

    monkeypatch.setattr(runtime_module.i3ipc, "Connection", connection)
    with pytest.raises(runtime_module.SwayIpcError, match="unsupported"):
        _runtime().focus_direction(direction)  # type: ignore[arg-type]


def test_focus_con_id_sends_exactly_one_selected_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []

    class Connection:
        def command(self, command: str) -> list[object]:
            commands.append(command)
            return [SimpleNamespace(success=True)]

    monkeypatch.setattr(runtime_module.i3ipc, "Connection", Connection)
    assert _runtime().focus_con_id(817263) is None
    assert commands == ["[con_id=817263] focus"]


@pytest.mark.parametrize("con_id", [True, False, "7", None])
def test_focus_con_id_rejects_non_integer_ids_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
    con_id: object,
) -> None:
    def connection() -> object:
        raise AssertionError("invalid con_id must not connect")

    monkeypatch.setattr(runtime_module.i3ipc, "Connection", connection)
    with pytest.raises(runtime_module.SwayIpcError, match="must be an integer"):
        _runtime().focus_con_id(con_id)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("replies", "message"),
    [
        ([], "returned no replies"),
        ([SimpleNamespace(success=False, error="denied")], "denied"),
        ([SimpleNamespace()], "command failed"),
        (None, "returned no replies"),
    ],
)
def test_command_reply_failures_are_normalized(
    monkeypatch: pytest.MonkeyPatch,
    replies: object,
    message: str,
) -> None:
    class Connection:
        def command(self, command: str) -> object:
            del command
            return replies

    monkeypatch.setattr(runtime_module.i3ipc, "Connection", Connection)
    with pytest.raises(runtime_module.SwayIpcError, match=message):
        _runtime().focus_direction("left")


def test_live_con_ids_uses_one_tree_read_and_returns_detached_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads = 0
    leaves = [SimpleNamespace(id=7), SimpleNamespace(id=11), SimpleNamespace(id=19)]

    class Tree:
        def leaves(self) -> list[object]:
            return leaves

    class Connection:
        def get_tree(self) -> Tree:
            nonlocal reads
            reads += 1
            return Tree()

    monkeypatch.setattr(runtime_module.i3ipc, "Connection", Connection)
    result = _runtime().live_con_ids()
    leaves[0].id = 99
    assert result == [7, 11, 19]
    assert reads == 1
    assert all(type(item) is int for item in result)


@pytest.mark.parametrize(
    "leaves",
    [
        [SimpleNamespace(id=True)],
        [SimpleNamespace(id="7")],
        [SimpleNamespace(id=7), SimpleNamespace(id=7)],
        None,
    ],
)
def test_live_con_ids_rejects_invalid_or_duplicate_leaf_ids(
    monkeypatch: pytest.MonkeyPatch,
    leaves: object,
) -> None:
    class Connection:
        def get_tree(self) -> object:
            return SimpleNamespace(leaves=lambda: leaves)

    monkeypatch.setattr(runtime_module.i3ipc, "Connection", Connection)
    with pytest.raises(runtime_module.SwayIpcError):
        _runtime().live_con_ids()
