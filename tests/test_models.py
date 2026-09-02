from __future__ import annotations

import pytest
from pydantic import ValidationError

from dix.elements.list import ListState
from dix.elements.selection import SelectionState
from dix.elements.value import ValueState
from dix.models import AccessSpec, InterfaceSpec


def test_access_session_match_requires_path() -> None:
    with pytest.raises(ValidationError):
        AccessSpec(mode="session_match")


def test_interface_rejects_duplicate_component_ids() -> None:
    with pytest.raises(ValidationError):
        InterfaceSpec.model_validate(
            {
                "interface": {"id": "demo", "title": "Demo"},
                "components": [
                    {"id": "same", "use": "input"},
                    {"id": "same", "use": "select"},
                ],
            }
        )


def test_value_state_set_and_clear() -> None:
    state = ValueState().set("hello")
    assert state.value == "hello"
    assert state.valid is True
    assert state.clear().value is None


def test_list_state_set_items() -> None:
    state = ListState().set_items([{"id": "a"}])
    assert state.items == [{"id": "a"}]


def test_selection_single_and_multi() -> None:
    single = SelectionState().select("a").toggle("a")
    assert single.selected is None

    multi = SelectionState(mode="multi").toggle("a").toggle("b").toggle("a")
    assert multi.selected == ["b"]
