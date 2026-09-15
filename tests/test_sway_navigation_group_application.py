from __future__ import annotations

from pathlib import Path

import pytest

import dix_sway_navigation_group_application_runtime_test_import as runtime_module
from dix.core.application import ApplicationRuntimeContext


class _Api:
    def __init__(self, functions):
        self.functions = functions
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def require(self, function_id: str):
        function = self.functions[function_id]
        def call(*args: object):
            self.calls.append((function_id, args))
            return function(*args)
        return call


class _Basic:
    def __init__(self, steps: list[tuple[int, int]]) -> None:
        self.steps = list(steps)
        self.calls: list[str] = []

    def require(self, function_id: str):
        def move():
            self.calls.append(function_id)
            origin, focused = self.steps.pop(0)
            return {
                "direction": function_id,
                "origin_id": origin,
                "focused_id": focused,
                "changed": focused != origin,
            }
        return move


def _runtime(
    *,
    members: object,
    live_ids: object,
    steps: list[tuple[int, int]],
    origin: object = 1,
    restored_focus: object = 1,
    restore_result: object = None,
):
    active_members = _Api({"get": lambda: members})
    focused_values = [origin, restored_focus]
    restore_calls: list[int] = []

    def focused():
        return focused_values.pop(0)

    def restore(con_id: int):
        restore_calls.append(con_id)
        return restore_result

    ipc = _Api({
        "focused_con_id": focused,
        "live_con_ids": lambda: live_ids,
        "focus_con_id": restore,
    })
    basic = _Basic(steps)
    context = ApplicationRuntimeContext(
        instance_id="navigation-group",
        application_id="dix/sway/navigation_group",
        module_id="dix/sway",
        module_root=Path("."),
        application_root=Path("."),
        config_base_dir=Path("."),
        owner_scope_id="test",
    )
    runtime = runtime_module.Runtime(
        context=context,
        config={},
        basic=basic,  # type: ignore[arg-type]
        active_members=active_members,
        ipc=ipc,
    )
    return runtime, basic, active_members, ipc, restore_calls


@pytest.mark.parametrize("direction", ["left", "right", "up", "down"])
def test_group_navigation_passes_intermediate_focus_and_hits_first_live_member(
    direction: str,
) -> None:
    runtime, basic, active_members, ipc, restore_calls = _runtime(
        members=[1, 3, 99],
        live_ids=[1, 2, 3],
        steps=[(1, 2), (2, 3)],
    )
    result = getattr(runtime, direction)()
    assert result == {
        "direction": direction,
        "origin_id": 1,
        "focused_id": 3,
        "matched": True,
        "restored": False,
        "visited_ids": [1, 2, 3],
        "stale_ids": [99],
    }
    assert list(result) == [
        "direction", "origin_id", "focused_id", "matched", "restored",
        "visited_ids", "stale_ids",
    ]
    assert basic.calls == [direction, direction]
    assert active_members.calls == [("get", ())]
    assert ipc.calls == [("focused_con_id", ()), ("live_con_ids", ())]
    assert restore_calls == []


def test_immediate_no_target_does_not_move_or_restore() -> None:
    runtime, basic, _, _, restore_calls = _runtime(
        members=[1, 99], live_ids=[1, 2], steps=[]
    )
    assert runtime.left() == {
        "direction": "left",
        "origin_id": 1,
        "focused_id": 1,
        "matched": False,
        "restored": True,
        "visited_ids": [1],
        "stale_ids": [99],
    }
    assert basic.calls == []
    assert restore_calls == []


def test_unchanged_step_terminates_without_redundant_restore() -> None:
    runtime, basic, _, _, restore_calls = _runtime(
        members=[1, 3], live_ids=[1, 2, 3], steps=[(1, 1)]
    )
    result = runtime.right()
    assert result["matched"] is False
    assert result["restored"] is True
    assert result["visited_ids"] == [1]
    assert basic.calls == ["right"]
    assert restore_calls == []


def test_repeated_focus_terminates_and_restores_only_when_needed() -> None:
    runtime, basic, _, _, restore_calls = _runtime(
        members=[1, 3],
        live_ids=[1, 2, 3],
        steps=[(1, 2), (2, 2)],
        restored_focus=1,
    )
    result = runtime.up()
    assert result == {
        "direction": "up",
        "origin_id": 1,
        "focused_id": 1,
        "matched": False,
        "restored": True,
        "visited_ids": [1, 2],
        "stale_ids": [],
    }
    assert basic.calls == ["up", "up"]
    assert restore_calls == [1]


def test_hard_live_count_limit_bounds_non_repeating_adapter_drift() -> None:
    runtime, basic, _, _, restore_calls = _runtime(
        members=[1, 3],
        live_ids=[1, 2, 3],
        steps=[(1, 2), (2, 4), (4, 5), (5, 6), (6, 7)],
        restored_focus=1,
    )
    result = runtime.down()
    assert result["matched"] is False
    assert result["visited_ids"] == [1, 2, 4, 5, 6]
    assert basic.calls == ["down"] * 4
    assert restore_calls == [1]


def test_restore_failure_is_visible() -> None:
    runtime, _, _, _, restore_calls = _runtime(
        members=[1, 3],
        live_ids=[1, 2, 3],
        steps=[(1, 2), (2, 2)],
        restored_focus=2,
    )
    with pytest.raises(RuntimeError, match="restore failed"):
        runtime.left()
    assert restore_calls == [1]


def test_non_none_restore_result_is_rejected() -> None:
    runtime, _, _, _, _ = _runtime(
        members=[1, 3],
        live_ids=[1, 2, 3],
        steps=[(1, 2), (2, 2)],
        restore_result=True,
    )
    with pytest.raises(TypeError, match="must return None"):
        runtime.left()


@pytest.mark.parametrize("members", [[], []])
def test_missing_or_empty_projection_delegates_exactly_once_without_ipc(members: list[int]) -> None:
    runtime, basic, active_members, ipc, restore_calls = _runtime(
        members=members, live_ids=AssertionError(), steps=[(1, 2)]
    )
    result = runtime.left()
    assert result == {"direction": "left", "origin_id": 1, "focused_id": 2, "changed": True}
    assert basic.calls == ["left"]
    assert active_members.calls == [("get", ())]
    assert ipc.calls == []
    assert restore_calls == []


def test_projection_error_precedes_every_ipc_call() -> None:
    runtime, basic, active_members, ipc, _ = _runtime(members=[], live_ids=[], steps=[])
    active_members.functions["get"] = lambda: (_ for _ in ()).throw(ValueError("corrupt projection"))
    with pytest.raises(ValueError, match="corrupt"):
        runtime.right()
    assert basic.calls == []
    assert ipc.calls == []


@pytest.mark.parametrize(
    ("members", "live_ids"),
    [
        ("bad", [1]),
        ([True], [1]),
        ([1, 1], [1]),
        ([1], "bad"),
        ([1], [True]),
        ([1], [1, 1]),
    ],
)
def test_invalid_group_or_live_id_results_fail_at_the_wrapper_boundary(
    members: object,
    live_ids: object,
) -> None:
    runtime, _, _, _, _ = _runtime(
        members=members, live_ids=live_ids, steps=[]
    )
    with pytest.raises((TypeError, ValueError)):
        runtime.left()


@pytest.mark.parametrize(
    "step",
    [
        None,
        {},
        {"direction": "left", "origin_id": 1, "focused_id": 2, "changed": True, "extra": 1},
        {"direction": "right", "origin_id": 1, "focused_id": 2, "changed": True},
        {"direction": "left", "origin_id": 9, "focused_id": 2, "changed": True},
        {"direction": "left", "origin_id": 1, "focused_id": True, "changed": True},
        {"direction": "left", "origin_id": 1, "focused_id": 2, "changed": False},
    ],
)
def test_invalid_basic_results_fail_at_the_wrapper_boundary(step: object) -> None:
    class Basic:
        def require(self, function_id: str):
            del function_id
            return lambda: step

    runtime, _, active_members, ipc, _ = _runtime(
        members=[1, 3], live_ids=[1, 2, 3], steps=[]
    )
    runtime.basic = Basic()  # type: ignore[assignment]
    with pytest.raises((TypeError, ValueError)):
        runtime.left()
    assert active_members.calls
    assert ipc.calls
