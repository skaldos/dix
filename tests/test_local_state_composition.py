from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import ValidationError

from dix.core import CompositionComponent, ModuleComponent, create_core_component_registry
from dix.core.composition import CompositionComponentError, CompositionInstanceSpec
from dix.modules import first_party_module_path


def _write_model(root: Path, *, required: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    model = root / "state_model.toml"
    title_default = "" if required else 'default = "worker"\n'
    model.write_text(
        """
name = "LocalState"

[fields.title]
type = "string"
help = "Human-readable state title."
"""
        + title_default
        + """
[fields.count]
type = "integer"
default = 1

[fields.metadata]
type = "object"
default = { tags = ["initial"] }

[fields.renderer]
type = "model"
name = "RendererState"
default = { theme = "dark" }

[fields.renderer.fields.theme]
type = "string"
"""
    )
    return model


def _components():
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    compositions = registry.require("composition", CompositionComponent)
    modules.load_module(first_party_module_path("dix/state"), module_id="dix/state")
    return registry, compositions


def _create(
    compositions: CompositionComponent,
    root: Path,
    *,
    instance_id: str = "state",
    scope: str = "test",
    initial: Mapping[str, object] | None = None,
):
    config: dict[str, object] = {"model": "state_model.toml"}
    if initial is not None:
        config["initial"] = initial
    return compositions.create_instance(
        CompositionInstanceSpec(instance_id, "dix/state/local", config, root),
        owner_scope_id=scope,
    )


def _find_cause(error: BaseException, expected: type[BaseException]) -> BaseException | None:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, expected):
            return current
        current = current.__cause__
    return None


def test_default_initial_state_and_function_surface(tmp_path: Path) -> None:
    _write_model(tmp_path)
    _, compositions = _components()
    instance = _create(compositions, tmp_path)

    assert {item.id for item in instance.api.functions()} == {"get", "set"}
    assert instance.api.require("get")() == {
        "title": "worker",
        "count": 1,
        "metadata": {"tags": ["initial"]},
        "renderer": {"theme": "dark"},
    }


def test_initial_values_are_validated_and_detached(tmp_path: Path) -> None:
    _write_model(tmp_path)
    _, compositions = _components()
    initial = {
        "title": "alpha",
        "count": "2",
        "metadata": {"tags": ["owner"]},
        "renderer": {"theme": "light"},
    }
    instance = _create(compositions, tmp_path, initial=initial)
    initial["metadata"]["tags"].append("mutated")  # type: ignore[index,union-attr]

    first = instance.api.require("get")()
    assert first["count"] == 2
    assert first["metadata"] == {"tags": ["owner"]}
    first["metadata"]["tags"].append("leak")
    first["renderer"]["theme"] = "mutated"
    assert instance.api.require("get")()["metadata"] == {"tags": ["owner"]}
    assert instance.api.require("get")()["renderer"] == {"theme": "light"}


def test_set_validates_full_candidates_and_reports_changes(tmp_path: Path) -> None:
    _write_model(tmp_path)
    _, compositions = _components()
    instance = _create(compositions, tmp_path)
    get = instance.api.require("get")
    set_value = instance.api.require("set")

    assert set_value(
        {
            "title": "worker",
            "count": "1",
            "metadata": {"tags": ["initial"]},
            "renderer": {"theme": "dark"},
        }
    ) is False
    changed = {
        "title": "changed",
        "count": 3,
        "metadata": {"tags": ["new"]},
        "renderer": {"theme": "light"},
    }
    assert set_value(changed) is True
    changed["metadata"]["tags"].append("caller-mutation")  # type: ignore[index,union-attr]
    assert get() == {
        "title": "changed",
        "count": 3,
        "metadata": {"tags": ["new"]},
        "renderer": {"theme": "light"},
    }

    before = get()
    with pytest.raises(ValidationError) as error:
        set_value(
            {
                "title": "broken",
                "count": "not-an-integer",
                "metadata": {},
                "renderer": {"theme": "dark"},
            }
        )
    assert error.value.errors()[0]["loc"] == ("count",)
    assert get() == before


def test_missing_initial_fails_when_required_fields_have_no_default(tmp_path: Path) -> None:
    _write_model(tmp_path, required=True)
    _, compositions = _components()

    with pytest.raises(CompositionComponentError) as error:
        _create(compositions, tmp_path)
    assert _find_cause(error.value, ValidationError) is not None


@pytest.mark.parametrize(
    ("configured", "prepare", "message"),
    [
        (None, lambda root: None, "non-empty string"),
        ("", lambda root: None, "non-empty string"),
        ("missing.toml", lambda root: None, "not a file"),
        ("directory", lambda root: (root / "directory").mkdir(), "not a file"),
        ("../outside.toml", lambda root: None, "escapes config base directory"),
    ],
)
def test_model_path_failures_are_visible(
    tmp_path: Path,
    configured: object,
    prepare,
    message: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.toml").write_text('name = "Outside"\nfields = {}\n')
    prepare(root)
    _, compositions = _components()

    with pytest.raises(CompositionComponentError, match=message):
        compositions.create_instance(
            CompositionInstanceSpec("state", "dix/state/local", {"model": configured}, root),
            owner_scope_id="test",
        )


def test_symlink_cannot_escape_model_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.toml"
    outside.write_text('name = "Outside"\nfields = {}\n')
    (root / "linked.toml").symlink_to(outside)
    _, compositions = _components()

    with pytest.raises(CompositionComponentError, match="escapes config base directory"):
        compositions.create_instance(
            CompositionInstanceSpec(
                "state", "dix/state/local", {"model": "linked.toml"}, root
            ),
            owner_scope_id="test",
        )


def test_absolute_model_path_is_rejected_even_within_root(tmp_path: Path) -> None:
    model = _write_model(tmp_path)
    _, compositions = _components()

    with pytest.raises(CompositionComponentError, match="must be relative"):
        compositions.create_instance(
            CompositionInstanceSpec(
                "state", "dix/state/local", {"model": str(model)}, tmp_path
            ),
            owner_scope_id="test",
        )


def test_invalid_toml_spec_and_initial_fail_during_creation(tmp_path: Path) -> None:
    _, compositions = _components()
    (tmp_path / "state_model.toml").write_text('name = "Broken"\n')
    with pytest.raises(CompositionComponentError, match="model.fields must be a mapping"):
        _create(compositions, tmp_path)

    _write_model(tmp_path)
    with pytest.raises(CompositionComponentError) as error:
        _create(compositions, tmp_path, initial={"count": "broken"})
    assert _find_cause(error.value, ValidationError) is not None


def test_root_instances_own_independent_values_and_model_types(tmp_path: Path) -> None:
    _write_model(tmp_path)
    _, compositions = _components()
    first = _create(
        compositions,
        tmp_path,
        instance_id="first",
        scope="owner",
        initial={"title": "first"},
    )
    second = _create(
        compositions,
        tmp_path,
        instance_id="second",
        scope="owner",
        initial={"title": "second"},
    )

    assert first.runtime._model_type is not second.runtime._model_type
    assert first.api.require("set")({"title": "changed"}) is True
    assert first.api.require("get")()["title"] == "changed"
    assert second.api.require("get")()["title"] == "second"
