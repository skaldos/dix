from __future__ import annotations

from pathlib import Path

import pytest

from dix.core import CompositionComponent, DatamodelComponent, create_core_component_registry
from dix.core.composition import CompositionComponentError, CompositionInstanceSpec


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


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def write_model(path: Path) -> Path:
    path.write_text(MODEL_TOML)
    return path


def datamodel_files_component(tmp_path: Path) -> tuple[CompositionComponent, object]:
    registry = create_core_component_registry()
    compositions = registry.require("composition", CompositionComponent)
    compositions.load_module(
        repo_root() / "examples" / "modules" / "dix" / "examples" / "files",
        module_id="dix/examples/files",
    )
    root = compositions.create_instance(
        CompositionInstanceSpec(
            id="data",
            use="dix/examples/files/datamodel_files",
            config={},
            config_base_dir=tmp_path,
        ),
        owner_scope_id="test",
    )
    return compositions, root


def test_direct_runtime_registers_model_and_loads_data(tmp_path: Path) -> None:
    _, root = datamodel_files_component(tmp_path)

    model = root.api.register_model(write_model(tmp_path / "model.toml"))
    result = root.api.load_data(DATA_JSON)

    assert model.definition.name == "user_request"
    assert model.definition.version == "1"
    assert result.compatible is True
    assert dict(result.values) == {
        "username": "alice",
        "age": 42,
        "metadata": {"source": "test"},
    }
    assert root.runtime.datamodel.registration_count == 1


def test_integer_wrapper_is_local_to_composition_datamodel(tmp_path: Path) -> None:
    _, root = datamodel_files_component(tmp_path)
    wrapped = root.api.register_model(write_model(tmp_path / "model.toml"))
    datamodel: DatamodelComponent = root.runtime.datamodel
    base = datamodel.register_model(wrapped.definition)

    wrapped_result = root.api.load_data(DATA_JSON)
    base_result = datamodel.instantiate(
        base,
        {"username": "alice", "age": "42", "metadata": {}},
    )

    assert wrapped_result.compatible is True
    assert wrapped_result.values["age"] == 42
    assert base_result.compatible is False


def test_runtime_rejects_invalid_model_and_data_input(tmp_path: Path) -> None:
    _, root = datamodel_files_component(tmp_path)
    invalid_model = tmp_path / "invalid.toml"
    invalid_model.write_text("[model\n")

    with pytest.raises(Exception, match="cannot load model file"):
        root.api.register_model(invalid_model)

    root.api.register_model(write_model(tmp_path / "model.toml"))
    with pytest.raises(Exception, match="invalid data input"):
        root.api.load_data("not-json")
    with pytest.raises(Exception, match="invalid data input"):
        root.api.load_data('{"model": {}, "data": {}}')


def test_runtime_rejects_unknown_and_ambiguous_local_models(tmp_path: Path) -> None:
    _, root = datamodel_files_component(tmp_path)

    with pytest.raises(Exception, match="not registered"):
        root.api.load_data(DATA_JSON)

    path = write_model(tmp_path / "model.toml")
    root.api.register_model(path)
    root.api.register_model(path)
    with pytest.raises(Exception, match="ambiguous"):
        root.api.load_data(DATA_JSON)


def test_two_roots_have_isolated_datamodel_registries(tmp_path: Path) -> None:
    compositions, first = datamodel_files_component(tmp_path)
    second = compositions.create_instance(
        CompositionInstanceSpec(
            id="other",
            use="dix/examples/files/datamodel_files",
            config={},
            config_base_dir=tmp_path,
        ),
        owner_scope_id="test",
    )

    first.api.register_model(write_model(tmp_path / "model.toml"))

    assert first.runtime.datamodel is not second.runtime.datamodel
    assert first.runtime.datamodel.registration_count == 1
    assert second.runtime.datamodel.registration_count == 0


def test_unknown_definition_is_rejected_without_legacy_factory_lookup(tmp_path: Path) -> None:
    registry = create_core_component_registry()
    compositions = registry.require("composition", CompositionComponent)

    with pytest.raises(CompositionComponentError, match="definition is not loaded"):
        compositions.create_instance(
            CompositionInstanceSpec("bad", "arbitrary/module/factory", {}, tmp_path),
            owner_scope_id="test",
        )
