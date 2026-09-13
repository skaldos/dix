from __future__ import annotations

from pathlib import Path

import pytest

import dix_sway_navigation_basic_application_runtime_test_import as runtime_module
from dix.core.application import ApplicationRuntimeContext


class _Ipc:
    def __init__(self, focuses: list[object], *, command_result: object = None) -> None:
        self.focuses = list(focuses)
        self.command_result = command_result
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def require(self, function_id: str):
        if function_id == "focused_con_id":
            def focused() -> object:
                self.calls.append((function_id, ()))
                return self.focuses.pop(0)
            return focused
        if function_id == "focus_direction":
            def focus(direction: str) -> object:
                self.calls.append((function_id, (direction,)))
                return self.command_result
            return focus
        raise AssertionError(function_id)


def _runtime(ipc: _Ipc) -> runtime_module.Runtime:
    context = ApplicationRuntimeContext(
        instance_id="navigation-basic",
        application_id="dix/sway/navigation_basic",
        module_id="dix/sway",
        module_root=Path("."),
        application_root=Path("."),
        config_base_dir=Path("."),
        owner_scope_id="test",
    )
    return runtime_module.Runtime(context=context, config={}, ipc=ipc)


@pytest.mark.parametrize("direction", ["left", "right", "up", "down"])
def test_each_direction_performs_exactly_one_native_step(direction: str) -> None:
    ipc = _Ipc([11, 19])
    runtime = _runtime(ipc)

    result = getattr(runtime, direction)()

    assert result == {
        "direction": direction,
        "origin_id": 11,
        "focused_id": 19,
        "changed": True,
    }
    assert list(result) == ["direction", "origin_id", "focused_id", "changed"]
    assert ipc.calls == [
        ("focused_con_id", ()),
        ("focus_direction", (direction,)),
        ("focused_con_id", ()),
    ]


def test_unchanged_native_focus_is_inspectable() -> None:
    result = _runtime(_Ipc([7, 7])).left()
    assert result == {
        "direction": "left",
        "origin_id": 7,
        "focused_id": 7,
        "changed": False,
    }


@pytest.mark.parametrize("focuses", [[True, 2], [1, "2"], [1, None]])
def test_invalid_focus_ids_fail_at_the_application_boundary(focuses: list[object]) -> None:
    with pytest.raises(TypeError, match="must return an integer"):
        _runtime(_Ipc(focuses)).right()


def test_non_none_command_result_fails_at_the_application_boundary() -> None:
    with pytest.raises(TypeError, match="must return None"):
        _runtime(_Ipc([1, 2], command_result=True)).up()


def test_ipc_errors_remain_visible() -> None:
    class Ipc:
        def require(self, function_id: str):
            if function_id == "focused_con_id":
                return lambda: 1
            if function_id == "focus_direction":
                def fail(direction: str) -> None:
                    del direction
                    raise RuntimeError("native failure")
                return fail
            raise AssertionError(function_id)

    with pytest.raises(RuntimeError, match="native failure"):
        _runtime(Ipc()).down()  # type: ignore[arg-type]
