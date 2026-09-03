from __future__ import annotations

from pathlib import Path

import pytest

from dix.compositions import (
    CompositionContext,
    CompositionError,
    CompositionOperationNotFound,
    CompositionRegistry,
    DatamodelFilesComposition,
    DatamodelFilesError,
    DatamodelFilesFactory,
)
from dix.core import DatamodelComponent, create_core_component_registry


MODEL_TOML = """
[model]
name = "user_request"
version = "1"

[fields.username]
type = "string"

[fields.age]
type = "integer"

[fields.metadata]
type = "any"
"""

DATA_JSON = """
{
  "model": {"name": "user_request", "version": "1"},
  "data": {
    "username": "alice",
    "age": "42",
    "metadata": {"source": "test"}
  }
}
"""


def write_model(path: Path) -> Path:
    path.write_text(MODEL_TOML)
    return path


def test_direct_composition_registers_model_and_loads_data(tmp_path: Path) -> None:
    datamodel = DatamodelComponent()
    composition = DatamodelFilesComposition(datamodel)

    model = composition.register_model(write_model(tmp_path / "model.toml"))
    result = composition.load_data(DATA_JSON)

    assert model.definition.name == "user_request"
    assert model.definition.version == "1"
    assert result.compatible is True
    assert dict(result.values) == {
        "username": "alice",
        "age": 42,
        "metadata": {"source": "test"},
    }
    assert datamodel.registration_count == 1


def test_composition_integer_wrapper_is_local_to_its_model(tmp_path: Path) -> None:
    datamodel = DatamodelComponent()
    composition = DatamodelFilesComposition(datamodel)
    wrapped = composition.register_model(write_model(tmp_path / "model.toml"))
    base = datamodel.register_model(wrapped.definition)

    wrapped_result = composition.load_data(DATA_JSON)
    base_result = datamodel.instantiate(
        base,
        {"username": "alice", "age": "42", "metadata": {}},
    )

    assert wrapped_result.compatible is True
    assert wrapped_result.values["age"] == 42
    assert base_result.compatible is False


def test_composition_rejects_invalid_model_and_data_input(tmp_path: Path) -> None:
    composition = DatamodelFilesComposition(DatamodelComponent())
    invalid_model = tmp_path / "invalid.toml"
    invalid_model.write_text("[model\n")

    with pytest.raises(DatamodelFilesError, match="cannot load model file"):
        composition.register_model(invalid_model)

    composition.register_model(write_model(tmp_path / "model.toml"))
    with pytest.raises(DatamodelFilesError, match="invalid data input"):
        composition.load_data("not-json")
    with pytest.raises(DatamodelFilesError, match="invalid data input"):
        composition.load_data('{"model": {}, "data": {}}')


def test_composition_rejects_unknown_and_ambiguous_local_models(tmp_path: Path) -> None:
    composition = DatamodelFilesComposition(DatamodelComponent())

    with pytest.raises(DatamodelFilesError, match="not registered"):
        composition.load_data(DATA_JSON)

    path = write_model(tmp_path / "model.toml")
    composition.register_model(path)
    composition.register_model(path)
    with pytest.raises(DatamodelFilesError, match="ambiguous"):
        composition.load_data(DATA_JSON)


def test_trusted_factory_resolves_paths_and_exposes_only_bound_operations(
    tmp_path: Path,
) -> None:
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    write_model(fixture_dir / "model.toml")
    (fixture_dir / "data.json").write_text(DATA_JSON)
    components = create_core_component_registry()
    registry = CompositionRegistry()
    registry.register(DatamodelFilesFactory())

    bound = registry.bind(
        "datamodel_files",
        CompositionContext(components=components, base_dir=tmp_path),
        {"model_path": "fixtures/model.toml", "data_path": "fixtures/data.json"},
    )
    payload = bound.invoke("run")

    assert payload["compatible"] is True
    assert payload["values"]["age"] == 42
    assert components.require("datamodel", DatamodelComponent).registration_count == 1
    with pytest.raises(CompositionOperationNotFound, match="does not expose"):
        bound.invoke("missing")


def test_registry_is_an_explicit_factory_allowlist(tmp_path: Path) -> None:
    registry = CompositionRegistry()
    factory = DatamodelFilesFactory()
    registry.register(factory)

    assert registry.ids() == ("datamodel_files",)
    assert registry.require("datamodel_files") is factory
    with pytest.raises(CompositionError, match="already registered"):
        registry.register(DatamodelFilesFactory())
    with pytest.raises(CompositionError, match="not found"):
        registry.bind(
            "arbitrary.module.Factory",
            CompositionContext(
                components=create_core_component_registry(),
                base_dir=tmp_path,
            ),
            {},
        )
