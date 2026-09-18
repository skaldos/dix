from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dix.core.composition import CompositionOwnerComponent, CompositionRuntimeContext


class KnotSpecificationError(ValueError):
    """Raised when a Knot specification is invalid."""


class KnotPathError(KnotSpecificationError):
    """Raised when an owner-local Knot model path is invalid."""


class KnotInputError(ValueError):
    """Raised when a Knot execution input is not a mapping."""


@dataclass(frozen=True)
class KnotFieldSpecification:
    name: str
    strand: str
    handler: str


@dataclass(frozen=True)
class KnotSpecification:
    id: str
    fields: tuple[KnotFieldSpecification, ...]
    path: Path


class Runtime:
    """Load and retain one immutable owner-local Knot specification."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
        owner: CompositionOwnerComponent,
    ) -> None:
        self.context = context
        self.config = config
        self.specification = _load_knot_specification(
            context.config_base_dir,
            config.get("model"),
        )
        self._strands: dict[str, Callable[[object], object]] = {}
        self._handlers: dict[str, Callable[[object], object]] = {}
        for field in self.specification.fields:
            if field.strand not in self._strands:
                self._strands[field.strand] = owner.bind_dependency(
                    field.strand,
                    "execute",
                )
            if field.handler not in self._handlers:
                self._handlers[field.handler] = owner.bind_function(field.handler)

    def execute(
        self,
        value: object,
    ) -> dict[str, object]:
        """Execute present known fields through immediate-owner bindings."""
        if not isinstance(value, Mapping):
            raise KnotInputError("knot input must be a mapping")

        results: dict[str, object] = {}
        for field in self.specification.fields:
            if field.name not in value:
                continue
            processed = self._strands[field.strand](value[field.name])
            results[field.name] = self._handlers[field.handler](processed)
        return results


def _load_knot_specification(base_dir: Path, configured_path: object) -> KnotSpecification:
    root = base_dir.expanduser().resolve()
    path = _resolve_owner_file(root, configured_path)
    document = _load_toml(path)
    _require_keys(document, {"knot", "fields"}, label="knot model")

    knot = _require_table(document["knot"], label="knot")
    _require_keys(knot, {"id"}, label="knot")
    knot_id = _require_identifier(knot["id"], label="knot.id")

    raw_fields = _require_table(document["fields"], label="fields")
    if not raw_fields:
        raise KnotSpecificationError("fields must not be empty")
    fields: list[KnotFieldSpecification] = []
    for raw_name, raw_field in raw_fields.items():
        name = _require_identifier(raw_name, label="field name")
        field = _require_table(raw_field, label=f"field '{name}'")
        _require_keys(field, {"strand", "handler"}, label=f"field '{name}'")
        strand = _require_identifier(field["strand"], label=f"field '{name}'.strand")
        handler = _require_identifier(field["handler"], label=f"field '{name}'.handler")
        if handler == "execute":
            raise KnotSpecificationError(f"field '{name}'.handler must not reference execute")
        fields.append(KnotFieldSpecification(name=name, strand=strand, handler=handler))
    return KnotSpecification(id=knot_id, fields=tuple(fields), path=path)


def _resolve_owner_file(root: Path, configured_path: object) -> Path:
    configured = _require_non_empty_string(configured_path, label="knot model path")
    relative = Path(configured)
    if relative.is_absolute():
        raise KnotPathError("knot model path must be relative to config base directory")
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise KnotPathError(f"knot model path escapes config base directory: {configured}")
    if not candidate.is_file():
        raise KnotPathError(f"knot model path is not a regular file: {configured}")
    return candidate


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise KnotSpecificationError(f"cannot parse knot model: {exc}") from exc


def _require_table(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise KnotSpecificationError(f"{label} must be a table")
    if any(not isinstance(key, str) for key in value):
        raise KnotSpecificationError(f"{label} keys must be strings")
    return value


def _require_keys(value: Mapping[str, Any], allowed: set[str], *, label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise KnotSpecificationError(f"{label} has unknown keys: {', '.join(unknown)}")
    missing = sorted(allowed - set(value))
    if missing:
        raise KnotSpecificationError(f"{label} is missing required keys: {', '.join(missing)}")


def _require_identifier(value: object, *, label: str) -> str:
    normalized = _require_non_empty_string(value, label=label)
    if not normalized.isidentifier():
        raise KnotSpecificationError(f"{label} must be a flat identifier: {normalized!r}")
    return normalized


def _require_non_empty_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KnotSpecificationError(f"{label} must be a non-empty string")
    return value.strip()
