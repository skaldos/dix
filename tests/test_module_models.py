from __future__ import annotations

from pathlib import Path

import pytest

from dix.core import (
    CompositionComponent,
    ModelNotLoaded,
    ModelReference,
    ModuleComponent,
    ModuleComponentError,
    create_core_component_registry,
)


def model_module(root: Path, *, field_type: str = "string") -> Path:
    path = root / "models" / "request" / "model.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        '[model]\n'
        'id = "request"\n'
        'version = "1"\n\n'
        '[fields.value]\n'
        f'type = "{field_type}"\n'
    )
    return root


def components() -> tuple[ModuleComponent, CompositionComponent]:
    registry = create_core_component_registry()
    return (
        registry.require("module", ModuleComponent),
        registry.require("composition", CompositionComponent),
    )


def test_model_only_module_inspects_loads_describes_and_unloads(tmp_path: Path) -> None:
    modules, _ = components()
    root = model_module(tmp_path / "module")
    reference = ModelReference("acme/models/request", "1")

    inspection = modules.inspect_module(root, module_id="acme/models")
    assert tuple(item.reference for item in inspection.model_definitions) == (reference,)

    loaded = modules.load_module(root, module_id="acme/models")
    assert tuple(loaded.models) == (reference,)
    assert modules.require_model(reference).definition.schema["value"].type == "string"
    assert modules.module_descriptors()[0].models == (reference,)

    modules.unload_module("acme/models")
    with pytest.raises(ModelNotLoaded):
        modules.require_model(reference)


def test_model_artifact_participates_in_module_digest(tmp_path: Path) -> None:
    modules, _ = components()
    root = model_module(tmp_path / "module")
    before = modules.inspect_module(root, module_id="acme/models").artifact_digest

    path = root / "models" / "request" / "model.toml"
    path.write_text(path.read_text().replace('type = "string"', 'type = "integer"'))

    after = modules.inspect_module(root, module_id="acme/models").artifact_digest
    assert before != after


def test_later_definition_failure_does_not_publish_staged_model(tmp_path: Path) -> None:
    modules, compositions = components()
    root = model_module(tmp_path / "module")
    composition = root / "compositions" / "broken"
    composition.mkdir(parents=True)
    (composition / "composition.toml").write_text('[composition]\nid = "broken"\n')
    (composition / "runtime.py").write_text(
        "class Runtime:\n"
        "    def __init__(self, *, context, config, unexpected): pass\n"
    )

    with pytest.raises(ModuleComponentError):
        modules.load_module(root, module_id="acme/models")

    assert modules.models() == ()
    assert modules.modules() == ()
    assert compositions.definitions() == ()
