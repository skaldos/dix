from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from dix.core.composition import CompositionRuntimeContext
from dix.core.element import CORE_ELEMENT_TYPES, ElementSpec


class StrandSpecificationError(ValueError):
    """Raised when a strand or model specification is invalid."""


class StrandPathError(StrandSpecificationError):
    """Raised when an owner-local specification path is invalid."""


class StrandBindingError(RuntimeError):
    """Reserved for failures while binding a normalized boundary."""


class StrandValueError(ValueError):
    """Reserved for incompatible values processed at runtime."""


@dataclass(frozen=True)
class ModelSpecification:
    name: str
    fields: Mapping[str, ElementSpec]
    path: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))


@dataclass(frozen=True)
class BoundarySpecification:
    type: str
    model: ModelSpecification | None = None


@dataclass(frozen=True)
class StrandSpecification:
    id: str
    input: BoundarySpecification
    output: BoundarySpecification
    path: Path


class Runtime:
    """Load and retain one immutable owner-local strand specification."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
    ) -> None:
        self.context = context
        self.config = config
        self.specification = _load_strand_specification(
            context.config_base_dir,
            config.get("spec"),
        )


def _load_strand_specification(base_dir: Path, configured_path: object) -> StrandSpecification:
    root = base_dir.expanduser().resolve()
    spec_path = _resolve_owner_file(root, root, configured_path, label="strand spec")
    document = _load_toml(spec_path, label="strand spec")
    _require_keys(document, {"strand", "input", "output"}, label="strand spec")

    strand = _require_table(document["strand"], label="strand")
    _require_keys(strand, {"id"}, label="strand")
    strand_id = _require_non_empty_string(strand["id"], label="strand.id")

    return StrandSpecification(
        id=strand_id,
        input=_normalize_boundary(
            document["input"],
            label="input",
            root=root,
            spec_path=spec_path,
        ),
        output=_normalize_boundary(
            document["output"],
            label="output",
            root=root,
            spec_path=spec_path,
        ),
        path=spec_path,
    )


def _normalize_boundary(
    raw: object,
    *,
    label: str,
    root: Path,
    spec_path: Path,
) -> BoundarySpecification:
    boundary = _require_table(raw, label=label)
    if "type" not in boundary:
        raise StrandSpecificationError(f"{label} is missing required key: type")
    type_name = _require_non_empty_string(boundary["type"], label=f"{label}.type")
    if type_name == "model":
        _require_keys(boundary, {"type", "model"}, label=label)
        model_path = _resolve_owner_file(
            root,
            spec_path.parent,
            boundary["model"],
            label=f"{label} model",
        )
        return BoundarySpecification(
            type="model",
            model=_load_model_specification(model_path),
        )
    _require_keys(boundary, {"type"}, label=label)
    if type_name not in CORE_ELEMENT_TYPES:
        raise StrandSpecificationError(f"{label}.type is not a native core element: {type_name}")
    return BoundarySpecification(type=type_name)


def _load_model_specification(path: Path) -> ModelSpecification:
    document = _load_toml(path, label="model spec")
    _require_keys(document, {"name", "fields"}, label="model spec")
    name = _require_non_empty_string(document["name"], label="model.name")
    fields = _require_table(document["fields"], label="model.fields")
    if not fields:
        raise StrandSpecificationError("model.fields must not be empty")

    normalized: dict[str, ElementSpec] = {}
    for raw_name, raw_field in fields.items():
        field_name = _require_non_empty_string(raw_name, label="model field name")
        if field_name in normalized:
            raise StrandSpecificationError(f"duplicate normalized model field: {field_name}")
        field = _require_table(raw_field, label=f"model field '{field_name}'")
        _require_keys(field, {"type"}, label=f"model field '{field_name}'")
        type_name = _require_non_empty_string(
            field["type"],
            label=f"model field '{field_name}'.type",
        )
        if type_name not in CORE_ELEMENT_TYPES:
            raise StrandSpecificationError(
                f"model field '{field_name}' type is not a native core element: {type_name}"
            )
        normalized[field_name] = ElementSpec(type_name)
    return ModelSpecification(name=name, fields=normalized, path=path)


def _resolve_owner_file(root: Path, parent: Path, raw_path: object, *, label: str) -> Path:
    configured = _require_non_empty_string(raw_path, label=f"{label} path")
    relative = Path(configured)
    if relative.is_absolute():
        raise StrandPathError(f"{label} path must be relative to config base directory")
    candidate = (parent / relative).resolve()
    if not candidate.is_relative_to(root):
        raise StrandPathError(f"{label} path escapes config base directory: {configured}")
    if not candidate.is_file():
        raise StrandPathError(f"{label} path is not a regular file: {configured}")
    return candidate


def _load_toml(path: Path, *, label: str) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise StrandSpecificationError(f"cannot parse {label}: {exc}") from exc


def _require_table(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StrandSpecificationError(f"{label} must be a table")
    if any(not isinstance(key, str) for key in value):
        raise StrandSpecificationError(f"{label} keys must be strings")
    return value


def _require_keys(value: Mapping[str, Any], allowed: set[str], *, label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise StrandSpecificationError(f"{label} has unknown keys: {', '.join(unknown)}")
    missing = sorted(allowed - set(value))
    if missing:
        raise StrandSpecificationError(f"{label} is missing required keys: {', '.join(missing)}")


def _require_non_empty_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StrandSpecificationError(f"{label} must be a non-empty string")
    return value.strip()
