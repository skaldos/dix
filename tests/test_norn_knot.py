from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dix.core import CompositionComponent, ModuleComponent, create_core_component_registry
from dix.core.composition import CompositionComponentError, CompositionInstanceSpec
from dix.modules import first_party_module_path


def _components() -> CompositionComponent:
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    compositions = registry.require("composition", CompositionComponent)
    modules.load_module(first_party_module_path("dix/norn"), module_id="dix/norn")
    return compositions


def _write_model(root: Path, body: str | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "knot.toml"
    path.write_text(
        body
        or """
[knot]
id = "theme"
[fields.focused]
strand = "client_colors"
handler = "set_focused"
[fields.urgent]
strand = "client_colors"
handler = "set_urgent"
"""
    )
    return path


def _create(root: Path, model: object = "knot.toml"):
    return _components().create_instance(
        CompositionInstanceSpec("knot", "dix/norn/knot", {"model": model}, root),
        owner_scope_id="test",
    )


def _root_cause(error: BaseException) -> BaseException:
    current = error
    while current.__cause__ is not None:
        current = current.__cause__
    return current


def test_knot_model_retains_declared_field_order(tmp_path: Path) -> None:
    path = _write_model(tmp_path)
    instance = _create(tmp_path)

    assert {item.id for item in instance.api.functions()} == {"execute"}
    assert instance.runtime.specification.id == "theme"
    assert instance.runtime.specification.path == path
    assert tuple(field.name for field in instance.runtime.specification.fields) == (
        "focused",
        "urgent",
    )
    assert instance.runtime.specification.fields[0].strand == "client_colors"
    assert instance.runtime.specification.fields[0].handler == "set_focused"


def test_execute_uses_model_order_and_ignores_missing_and_unknown_fields(tmp_path: Path) -> None:
    _write_model(tmp_path)
    execute = _create(tmp_path).api.require("execute")
    calls: list[tuple[str, object]] = []

    def strand(value: object) -> object:
        calls.append(("strand", value))
        return f"processed:{value}"

    def focused(value: object) -> object:
        calls.append(("focused", value))
        return "focused-result"

    def urgent(value: object) -> object:
        calls.append(("urgent", value))
        return "urgent-result"

    result = execute(
        {"unknown": 9, "urgent": "u", "focused": "f"},
        {"client_colors": strand, "unused": lambda value: value},
        {
            "set_urgent": urgent,
            "set_focused": focused,
            "unused": lambda value: value,
        },
    )

    assert result == {"focused": "focused-result", "urgent": "urgent-result"}
    assert calls == [
        ("strand", "f"),
        ("focused", "processed:f"),
        ("strand", "u"),
        ("urgent", "processed:u"),
    ]
    assert execute({}, {"client_colors": strand}, {"set_focused": focused, "set_urgent": urgent}) == {}


def test_execute_validates_all_bindings_before_first_call(tmp_path: Path) -> None:
    _write_model(tmp_path)
    execute = _create(tmp_path).api.require("execute")
    calls: list[object] = []

    with pytest.raises(Exception, match="missing handler binding: set_urgent") as captured:
        execute(
            {"focused": "f"},
            {"client_colors": lambda value: calls.append(value)},
            {"set_focused": lambda value: calls.append(value)},
        )
    assert type(captured.value).__name__ == "KnotBindingError"
    assert calls == []


@pytest.mark.parametrize(
    "value,strands,handlers,match",
    [
        ([], {}, {}, "input must be a mapping"),
        ({}, [], {}, "strand bindings must be a mapping"),
        ({}, {}, [], "handler bindings must be a mapping"),
        ({}, {"bad.name": lambda value: value}, {}, "flat identifiers"),
        ({}, {"client_colors": object()}, {}, "not callable"),
    ],
)
def test_execute_rejects_invalid_input_or_binding_tables(
    tmp_path: Path,
    value: object,
    strands: object,
    handlers: object,
    match: str,
) -> None:
    _write_model(tmp_path)
    execute = _create(tmp_path).api.require("execute")
    with pytest.raises(Exception, match=match):
        execute(value, strands, handlers)


def test_execute_rejects_async_bindings_before_calls(tmp_path: Path) -> None:
    _write_model(tmp_path)
    execute = _create(tmp_path).api.require("execute")

    async def async_strand(value: object) -> object:
        return value

    with pytest.raises(Exception, match="must be synchronous") as captured:
        execute(
            {"focused": "f"},
            {"client_colors": async_strand},
            {"set_focused": lambda value: value, "set_urgent": lambda value: value},
        )
    assert type(captured.value).__name__ == "KnotBindingError"


def test_execute_preserves_callable_errors_and_stops(tmp_path: Path) -> None:
    _write_model(tmp_path)
    execute = _create(tmp_path).api.require("execute")
    expected = LookupError("domain failure")
    calls: list[str] = []

    def fail(value: object) -> Any:
        calls.append(f"focused:{value}")
        raise expected

    with pytest.raises(LookupError) as captured:
        execute(
            {"focused": "f", "urgent": "u"},
            {"client_colors": lambda value: value},
            {"set_focused": fail, "set_urgent": lambda value: calls.append("urgent")},
        )
    assert captured.value is expected
    assert calls == ["focused:f"]


@pytest.mark.parametrize(
    "body,match",
    [
        ("[knot]\nid='x'\nextra=true\n[fields.a]\nstrand='s'\nhandler='h'\n", "unknown"),
        ("[knot]\nid='x'\n[fields]\n", "must not be empty"),
        ("[knot]\nid='x'\n[fields.'bad.name']\nstrand='s'\nhandler='h'\n", "flat identifier"),
        ("[knot]\nid='x'\n[fields.a]\nstrand='bad.name'\nhandler='h'\n", "flat identifier"),
        ("[knot]\nid='x'\n[fields.a]\nstrand='s'\nhandler='bad.name'\n", "flat identifier"),
        ("[knot]\nid='x'\n[fields.a]\nstrand='s'\nhandler='execute'\n", "must not reference"),
        ("[knot]\nid='x'\n[fields.a]\nstrand='s'\nhandler='h'\nextra=true\n", "unknown"),
    ],
)
def test_knot_model_rejects_invalid_contracts(tmp_path: Path, body: str, match: str) -> None:
    _write_model(tmp_path, body)
    with pytest.raises(CompositionComponentError) as captured:
        _create(tmp_path)
    assert match in str(_root_cause(captured.value))


def test_knot_model_path_rejects_absolute_missing_directory_and_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.toml"
    outside.write_text("[knot]\nid='x'\n[fields.a]\nstrand='s'\nhandler='h'\n")
    (tmp_path / "directory").mkdir()

    for configured in (str(outside), "missing.toml", "directory", f"../{outside.name}"):
        with pytest.raises(CompositionComponentError) as captured:
            _create(tmp_path, configured)
        assert "path" in str(_root_cause(captured.value))


def test_knot_model_symlink_escape_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.toml"
    outside.write_text("[knot]\nid='x'\n[fields.a]\nstrand='s'\nhandler='h'\n")
    (tmp_path / "link.toml").symlink_to(outside)

    with pytest.raises(CompositionComponentError) as captured:
        _create(tmp_path, "link.toml")
    assert "escapes" in str(_root_cause(captured.value))
