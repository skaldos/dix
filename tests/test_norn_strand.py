from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

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


def _write_atomic(root: Path, body: str | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "strand.toml"
    path.write_text(
        body
        or """
[strand]
id = "atomic"
[input]
type = "string"
[output]
type = "integer"
"""
    )
    return path


def _create(root: Path, spec: object = "strand.toml"):
    return _components().create_instance(
        CompositionInstanceSpec("strand", "dix/norn/strand", {"spec": spec}, root),
        owner_scope_id="test",
    )


def _root_cause(error: BaseException) -> BaseException:
    current = error
    while current.__cause__ is not None:
        current = current.__cause__
    return current


def test_atomic_spec_is_normalized_immutably_without_public_functions(tmp_path: Path) -> None:
    _write_atomic(tmp_path)
    instance = _create(tmp_path)

    assert instance.api.functions() == ()
    assert instance.runtime.specification.id == "atomic"
    assert instance.runtime.specification.input.type == "string"
    assert instance.runtime.specification.output.type == "integer"


def test_model_spec_is_flat_native_and_immutable(tmp_path: Path) -> None:
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "colors.toml").write_text(
        """
name = "Colors"
[fields.border]
type = "string"
[fields.priority]
type = "integer"
"""
    )
    _write_atomic(
        tmp_path,
        """
[strand]
id = "colors"
[input]
type = "model"
model = "models/colors.toml"
[output]
type = "model"
model = "models/colors.toml"
""",
    )

    specification = _create(tmp_path).runtime.specification
    model = specification.input.model
    assert model is not None
    assert model.name == "Colors"
    assert isinstance(model.fields, MappingProxyType)
    assert tuple(model.fields) == ("border", "priority")
    with pytest.raises(TypeError):
        model.fields["new"] = model.fields["border"]


@pytest.mark.parametrize(
    "body,match",
    [
        ("[strand]\nid='x'\nextra=true\n[input]\ntype='string'\n[output]\ntype='string'\n", "unknown keys"),
        ("[strand]\nid='x'\n[input]\ntype='choice'\n[output]\ntype='string'\n", "not a native"),
        ("[strand]\nid='x'\n[input]\ntype='model'\n[output]\ntype='string'\n", "missing required keys"),
        ("[strand]\nid='x'\n[input]\ntype='string'\nmodel='x.toml'\n[output]\ntype='string'\n", "unknown keys"),
    ],
)
def test_strand_spec_rejects_unknown_or_invalid_boundaries(
    tmp_path: Path,
    body: str,
    match: str,
) -> None:
    _write_atomic(tmp_path, body)
    with pytest.raises(CompositionComponentError) as captured:
        _create(tmp_path)
    assert match in str(_root_cause(captured.value))


@pytest.mark.parametrize(
    "model,match",
    [
        ("name='X'\n[fields]\n", "must not be empty"),
        ("name='X'\n[fields.value]\ntype='string'\ndefault='x'\n", "unknown keys"),
        ("name='X'\n[fields.value]\ntype='model'\n", "not a native"),
        ("name='X'\n[fields.' ']\ntype='string'\n", "must be a non-empty string"),
    ],
)
def test_model_spec_rejects_non_slice_semantics(tmp_path: Path, model: str, match: str) -> None:
    (tmp_path / "model.toml").write_text(model)
    _write_atomic(
        tmp_path,
        "[strand]\nid='x'\n[input]\ntype='model'\nmodel='model.toml'\n[output]\ntype='string'\n",
    )
    with pytest.raises(CompositionComponentError) as captured:
        _create(tmp_path)
    assert match in str(_root_cause(captured.value))


def test_spec_path_rejects_absolute_missing_directory_and_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.toml"
    outside.write_text("[strand]\nid='x'\n[input]\ntype='string'\n[output]\ntype='string'\n")
    (tmp_path / "directory").mkdir()

    for configured in (str(outside), "missing.toml", "directory", f"../{outside.name}"):
        with pytest.raises(CompositionComponentError) as captured:
            _create(tmp_path, configured)
        assert "path" in str(_root_cause(captured.value))


def test_spec_and_model_symlink_escapes_are_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.toml"
    outside.write_text("[strand]\nid='x'\n[input]\ntype='string'\n[output]\ntype='string'\n")
    (tmp_path / "strand-link.toml").symlink_to(outside)
    with pytest.raises(CompositionComponentError) as captured:
        _create(tmp_path, "strand-link.toml")
    assert "escapes" in str(_root_cause(captured.value))

    (tmp_path / "model-link.toml").symlink_to(outside)
    _write_atomic(
        tmp_path,
        "[strand]\nid='x'\n[input]\ntype='model'\nmodel='model-link.toml'\n[output]\ntype='string'\n",
    )
    with pytest.raises(CompositionComponentError) as captured:
        _create(tmp_path)
    assert "escapes" in str(_root_cause(captured.value))
