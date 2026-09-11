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
