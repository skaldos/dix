from __future__ import annotations

from pathlib import Path

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


def test_knot_model_retains_declared_field_order_without_functions(tmp_path: Path) -> None:
    path = _write_model(tmp_path)
    instance = _create(tmp_path)

    assert instance.api.functions() == ()
    assert instance.runtime.specification.id == "theme"
    assert instance.runtime.specification.path == path
    assert tuple(field.name for field in instance.runtime.specification.fields) == (
        "focused",
        "urgent",
    )
    assert instance.runtime.specification.fields[0].strand == "client_colors"
    assert instance.runtime.specification.fields[0].handler == "set_focused"


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
