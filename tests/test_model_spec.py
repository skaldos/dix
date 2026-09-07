from __future__ import annotations

from pathlib import Path

import pytest

from dix.core import ModelSpecError, inspect_model_spec


def write_model(root: Path, body: str, *, name: str = "request") -> Path:
    path = root / "models" / name / "model.toml"
    path.parent.mkdir(parents=True)
    path.write_text(body)
    return path


def valid_model() -> str:
    return (
        '[model]\n'
        'id = "request"\n'
        'version = "1"\n\n'
        '[fields.name]\n'
        'type = "string"\n\n'
        '[fields.count]\n'
        'type = "integer"\n'
    )


def test_model_spec_is_code_free_namespaced_and_deterministic(tmp_path: Path) -> None:
    path = write_model(tmp_path, valid_model())

    first = inspect_model_spec(path, module_id="acme/models")
    second = inspect_model_spec(path, module_id="acme/models")

    assert first.id == "acme/models/request"
    assert first.local_id == "request"
    assert first.module_id == "acme/models"
    assert first.version == "1"
    assert first.reference.use == first.id
    assert first.reference.version == "1"
    assert first.definition.uid == second.definition.uid
    assert first.definition.name == first.id
    assert list(first.definition.schema) == ["name", "count"]
    assert first.definition.schema["name"].type == "string"
    assert first.definition.schema["count"].type == "integer"


def test_model_spec_preserves_unresolved_element_declaration(tmp_path: Path) -> None:
    body = valid_model().replace('type = "string"', 'type = "acme/encrypted"', 1)

    definition = inspect_model_spec(
        write_model(tmp_path, body),
        module_id="acme/models",
    )

    assert definition.definition.schema["name"].type == "acme/encrypted"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (valid_model().replace('id = "request"', 'id = "other"'), "does not match"),
        (valid_model().replace('[fields.name]\n', '[fields.name]\nunknown = true\n'), "unknown"),
        ('[model]\nid = "request"\n[fields]\n', "at least one"),
    ],
)
def test_model_spec_rejects_invalid_structure(
    tmp_path: Path,
    body: str,
    message: str,
) -> None:
    with pytest.raises(ModelSpecError, match=message):
        inspect_model_spec(write_model(tmp_path, body), module_id="acme/models")
