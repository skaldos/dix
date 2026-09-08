from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from dix.core import CompositionComponent, ModuleComponent, create_core_component_registry
from dix.core.composition import CompositionInstanceSpec
from dix.modules import first_party_module_path


def _resolve(tmp_path: Path) -> Callable[[Mapping[str, object]], type[BaseModel]]:
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    compositions = registry.require("composition", CompositionComponent)
    modules.load_module(first_party_module_path("dix/config"), module_id="dix/config")
    instance = compositions.create_instance(
        CompositionInstanceSpec("config", "dix/config/pydantic", {}, tmp_path),
        owner_scope_id="test",
    )
    return instance.api.require("resolve")


def _complete_spec() -> dict[str, object]:
    return {
        "name": "ServiceConfig",
        "fields": {
            "anything": {"type": "any", "default": None},
            "title": {"type": "string", "help": "Human-readable service title."},
            "retries": {"type": "integer", "default": 2},
            "ratio": {"type": "number", "default": 0.5},
            "enabled": {"type": "boolean", "default": True},
            "metadata": {"type": "object", "default": {}},
            "items": {"type": "array", "default": []},
            "renderer": {
                "type": "model",
                "name": "RendererConfig",
                "fields": {
                    "upper": {"type": "boolean", "default": False},
                    "label": {"type": "string"},
                },
            },
        },
    }


def test_resolve_builds_real_model_with_all_types_and_metadata(tmp_path: Path) -> None:
    resolve = _resolve(tmp_path)
    model = resolve(_complete_spec())

    assert issubclass(model, BaseModel)
    assert model.__name__ == "ServiceConfig"
    assert model.model_config["validate_default"] is True
    assert model.model_fields["title"].is_required()
    assert model.model_fields["title"].description == "Human-readable service title."
    assert not model.model_fields["anything"].is_required()
    assert model.model_fields["anything"].annotation is Any
    assert model.model_fields["title"].annotation is str
    assert model.model_fields["retries"].annotation is int
    assert model.model_fields["ratio"].annotation is float
    assert model.model_fields["enabled"].annotation is bool
    assert model.model_fields["metadata"].annotation == dict[str, object]
    assert model.model_fields["items"].annotation == list[object]

    value = model.model_validate(
        {
            "title": "worker",
            "renderer": {"label": "compact"},
        }
    )
    assert value.model_dump() == {
        "anything": None,
        "title": "worker",
        "retries": 2,
        "ratio": 0.5,
        "enabled": True,
        "metadata": {},
        "items": [],
        "renderer": {"upper": False, "label": "compact"},
    }
    assert isinstance(value.renderer, BaseModel)
    assert value.renderer.__class__.__name__ == "RendererConfig"


def test_owner_validates_values_and_receives_pydantic_errors(tmp_path: Path) -> None:
    model = _resolve(tmp_path)(_complete_spec())

    with pytest.raises(ValidationError) as missing:
        model.model_validate({"renderer": {"label": "compact"}})
    assert missing.value.errors()[0]["loc"] == ("title",)

    with pytest.raises(ValidationError) as incompatible:
        model.model_validate(
            {"title": "worker", "retries": "not-an-int", "renderer": {"label": "x"}}
        )
    assert incompatible.value.errors()[0]["loc"] == ("retries",)


def test_invalid_default_is_checked_when_owner_instantiates_model(tmp_path: Path) -> None:
    model = _resolve(tmp_path)(
        {
            "name": "InvalidDefault",
            "fields": {"count": {"type": "integer", "default": "invalid"}},
        }
    )
    with pytest.raises(ValidationError) as error:
        model()
    assert error.value.errors()[0]["loc"] == ("count",)


def test_each_resolve_call_returns_an_independent_model_type(tmp_path: Path) -> None:
    resolve = _resolve(tmp_path)
    spec = {"name": "LocalConfig", "fields": {"value": {"type": "string"}}}

    first = resolve(spec)
    second = resolve(spec)

    assert first is not second
    assert first.model_validate({"value": "first"}).value == "first"
    assert second.model_validate({"value": "second"}).value == "second"


def test_internal_normalized_specs_are_inspectable_and_immutable(tmp_path: Path) -> None:
    resolve = _resolve(tmp_path)
    runtime_module = sys.modules[resolve.__self__.__class__.__module__]
    normalized = runtime_module._normalize_model(_complete_spec(), location="model")

    assert normalized.name == "ServiceConfig"
    assert tuple(field.name for field in normalized.fields) == (
        "anything",
        "title",
        "retries",
        "ratio",
        "enabled",
        "metadata",
        "items",
        "renderer",
    )
    assert normalized.fields[-1].model.name == "RendererConfig"
    with pytest.raises(FrozenInstanceError):
        normalized.name = "Changed"


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ({}, "model.name must be a non-empty string"),
        ({"name": "X"}, "model.fields must be a mapping"),
        ({"name": "X", "fields": {"x": {}}}, "model.fields.x.type"),
        (
            {"name": "X", "fields": {"x": {"type": "unknown"}}},
            "unsupported value: unknown",
        ),
        (
            {"name": "X", "fields": {"x": {"type": "string", "items": {}}}},
            "contains unknown keys: items",
        ),
        (
            {"name": "X", "fields": {"x": {"type": "model", "name": "Y"}}},
            "model.fields must be a mapping",
        ),
    ],
)
def test_invalid_specs_fail_before_model_creation(
    tmp_path: Path,
    spec: Mapping[str, object],
    message: str,
) -> None:
    resolve = _resolve(tmp_path)
    with pytest.raises(ValueError, match=message):
        resolve(spec)
