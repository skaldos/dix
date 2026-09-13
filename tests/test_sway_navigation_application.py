from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

import dix_sway_navigation_application_runtime_test_import as runtime_module
from dix.core.application import ApplicationRuntimeContext


class _State:
    def __init__(self, selector: object = "basic") -> None:
        self.value = {"node_selector": selector}
        self.writes: list[dict[str, object]] = []

    def require(self, function_id: str):
        if function_id == "get":
            return lambda: deepcopy(self.value)
        if function_id == "set":
            def set_value(value: dict[str, object]) -> bool:
                changed = value != self.value
                self.writes.append(deepcopy(value))
                self.value = deepcopy(value)
                return changed
            return set_value
        raise AssertionError(function_id)


class _Target:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[str] = []

    def require(self, function_id: str):
        def move():
            self.calls.append(function_id)
            return {"target": self.name, "direction": function_id}
        return move


def _runtime(state: _State | None = None):
    state = state or _State()
    basic = _Target("basic")
    group = _Target("group")
    context = ApplicationRuntimeContext(
        instance_id="navigation",
        application_id="dix/sway/navigation",
        module_id="dix/sway",
        module_root=Path("."),
        application_root=Path("."),
        config_base_dir=Path("."),
        owner_scope_id="test",
    )
    runtime = runtime_module.Runtime(
        context=context,
        config={},
        state=state,
        basic=basic,  # type: ignore[arg-type]
        group=group,  # type: ignore[arg-type]
    )
    return runtime, state, basic, group


def test_default_selector_is_basic_and_select_is_an_explicit_state_write() -> None:
    runtime, state, _, _ = _runtime()
    assert runtime.current() == "basic"
    assert runtime.select("group") is True
    assert runtime.current() == "group"
    assert runtime.select("group") is False
    assert state.writes == [
        {"node_selector": "group"},
        {"node_selector": "group"},
    ]


@pytest.mark.parametrize("selector", ["", "other", "BASIC", None, 1])
def test_select_rejects_unknown_values_without_state_mutation(selector: object) -> None:
    runtime, state, _, _ = _runtime()
    with pytest.raises(ValueError, match="unknown"):
        runtime.select(selector)  # type: ignore[arg-type]
    assert state.value == {"node_selector": "basic"}
    assert state.writes == []


@pytest.mark.parametrize("direction", ["left", "right", "up", "down"])
@pytest.mark.parametrize("selector", ["basic", "group"])
def test_each_direction_routes_only_to_the_selected_composed_app(
    selector: str,
    direction: str,
) -> None:
    runtime, _, basic, group = _runtime(_State(selector))
    result = getattr(runtime, direction)()
    assert result == {"target": selector, "direction": direction}
    selected = basic if selector == "basic" else group
    other = group if selector == "basic" else basic
    assert selected.calls == [direction]
    assert other.calls == []


@pytest.mark.parametrize("selector", ["unknown", "", None, 1])
def test_injected_unknown_state_fails_for_current_and_routing(selector: object) -> None:
    runtime, _, basic, group = _runtime(_State(selector))
    with pytest.raises(ValueError, match="unknown"):
        runtime.current()
    with pytest.raises(ValueError, match="unknown"):
        runtime.left()
    assert basic.calls == []
    assert group.calls == []


def test_non_mapping_state_and_target_results_are_rejected() -> None:
    runtime, state, basic, _ = _runtime()
    state.require = lambda function_id: lambda: None  # type: ignore[method-assign]
    with pytest.raises(TypeError, match="state must be a mapping"):
        runtime.current()

    runtime, _, basic, _ = _runtime()
    basic.require = lambda function_id: lambda: None  # type: ignore[method-assign]
    with pytest.raises(TypeError, match="must return a mapping"):
        runtime.right()
