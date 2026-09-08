from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from dix.core.composition import CompositionRuntimeContext

StateTypeName = Literal[
    "any",
    "string",
    "integer",
    "number",
    "boolean",
    "object",
    "array",
    "model",
]

_MISSING = object()
_MODEL_KEYS = frozenset({"name", "fields"})
_FIELD_KEYS = frozenset({"type", "default", "help"})
_NESTED_MODEL_KEYS = _FIELD_KEYS | _MODEL_KEYS
_PRIMITIVE_TYPES: dict[str, object] = {
    "any": Any,
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict[str, object],
    "array": list[object],
}


class StateModelSpecError(ValueError):
    """Raised when a declarative state model specification is structurally invalid."""


@dataclass(frozen=True, slots=True)
class StateFieldSpec:
    """Normalized immutable description of one state field."""

    name: str
    type: StateTypeName
    default: object = _MISSING
    description: str | None = None
    model: StateModelSpec | None = None

    @property
    def required(self) -> bool:
        return self.default is _MISSING


@dataclass(frozen=True, slots=True)
class StateModelSpec:
    """Normalized immutable description of one state model."""

    name: str
    fields: tuple[StateFieldSpec, ...]


class Runtime:
    """Resolve owner-provided declarative specifications into Pydantic model types."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
    ) -> None:
        self.context = context
        self.config = config

    def resolve(self, spec: Mapping[str, object]) -> type[BaseModel]:
        """Resolve a declarative state model specification into a Pydantic model type."""
        return _build_model(_normalize_model(spec, location="model"))


def _normalize_model(spec: Mapping[str, object], *, location: str) -> StateModelSpec:
    mapping = _mapping(spec, location)
    _reject_unknown_keys(mapping, _MODEL_KEYS, location)
    name = _nonempty_string(mapping.get("name"), f"{location}.name")
    fields_mapping = _mapping(mapping.get("fields"), f"{location}.fields")
    fields: list[StateFieldSpec] = []
    for field_name, field_value in fields_mapping.items():
        normalized_name = _nonempty_string(field_name, f"{location}.fields key")
        fields.append(
            _normalize_field(
                normalized_name,
                field_value,
                location=f"{location}.fields.{normalized_name}",
            )
        )
    return StateModelSpec(name=name, fields=tuple(fields))


def _normalize_field(name: str, value: object, *, location: str) -> StateFieldSpec:
    mapping = _mapping(value, location)
    type_name = _nonempty_string(mapping.get("type"), f"{location}.type")
    if type_name not in {*_PRIMITIVE_TYPES, "model"}:
        raise StateModelSpecError(f"{location}.type has unsupported value: {type_name}")
    description_value = mapping.get("help")
    description = (
        None
        if description_value is None
        else _nonempty_string(description_value, f"{location}.help")
    )
    default = mapping.get("default", _MISSING)

    if type_name == "model":
        _reject_unknown_keys(mapping, _NESTED_MODEL_KEYS, location)
        nested = _normalize_model(
            {"name": mapping.get("name"), "fields": mapping.get("fields")},
            location=f"{location}.model",
        )
        return StateFieldSpec(
            name=name,
            type="model",
            default=default,
            description=description,
            model=nested,
        )

    _reject_unknown_keys(mapping, _FIELD_KEYS, location)
    return StateFieldSpec(
        name=name,
        type=type_name,  # type: ignore[arg-type]
        default=default,
        description=description,
    )


def _build_model(spec: StateModelSpec) -> type[BaseModel]:
    definitions: dict[str, tuple[object, object]] = {}
    for field in spec.fields:
        annotation = (
            _build_model(field.model)
            if field.type == "model" and field.model is not None
            else _PRIMITIVE_TYPES[field.type]
        )
        default = ... if field.required else field.default
        definitions[field.name] = (
            annotation,
            Field(default=default, description=field.description),
        )
    try:
        return create_model(
            spec.name,
            __config__=ConfigDict(validate_default=True),
            **definitions,
        )
    except Exception as exc:
        raise StateModelSpecError(f"cannot create state model '{spec.name}': {exc}") from exc


def _mapping(value: object, location: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise StateModelSpecError(f"{location} must be a mapping")
    for key in value:
        if not isinstance(key, str):
            raise StateModelSpecError(f"{location} keys must be strings")
    return value


def _nonempty_string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StateModelSpecError(f"{location} must be a non-empty string")
    return value.strip()


def _reject_unknown_keys(
    mapping: Mapping[str, object],
    allowed: frozenset[str],
    location: str,
) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise StateModelSpecError(f"{location} contains unknown keys: {', '.join(unknown)}")
