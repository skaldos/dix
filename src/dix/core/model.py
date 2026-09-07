from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from dix.core.datamodel import ModelDefinition
from dix.core.element import ElementSpec
from dix.core.module.errors import ModuleSpecError
from dix.core.module.validation import canonical_file, normalize_local_id, normalize_module_id


class ModelSpecError(ModuleSpecError):
    """Raised when a declarative model artifact is invalid."""


class ModelNotLoaded(LookupError):
    """Raised when an exact model artifact identity is not loaded."""


@dataclass(frozen=True, order=True)
class ModelReference:
    use: str
    version: str | None = None

    def __post_init__(self) -> None:
        try:
            use = normalize_module_id(self.use)
        except ModuleSpecError as exc:
            raise ValueError(f"invalid model reference: {self.use!r}") from exc
        version = self.version
        if version is not None:
            version = version.strip()
            if not version:
                raise ValueError("model reference version must not be empty")
        object.__setattr__(self, "use", use)
        object.__setattr__(self, "version", version)


@dataclass(frozen=True)
class ModelArtifactDefinition:
    id: str
    local_id: str
    module_id: str
    version: str | None
    definition: ModelDefinition
    spec_path: Path

    @property
    def reference(self) -> ModelReference:
        return ModelReference(self.id, self.version)


def inspect_model_spec(path: Path, *, module_id: str) -> ModelArtifactDefinition:
    """Parse one code-free model artifact without resolving element handlers."""
    normalized_module_id = normalize_module_id(module_id)
    spec_path = canonical_file(path, label="model spec")
    if spec_path.name != "model.toml":
        raise ModelSpecError(f"model spec must be named model.toml: {spec_path}")
    model_root = spec_path.parent
    models_root = model_root.parent
    if models_root.name != "models":
        raise ModelSpecError(
            f"model spec must be directly below a models directory: {spec_path}"
        )
    try:
        raw = tomllib.loads(spec_path.read_text())
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ModelSpecError(f"cannot read model spec {spec_path}: {exc}") from exc
    _reject_unknown(raw, {"model", "fields"}, "model spec")

    header = _mapping(raw.get("model"), "model")
    _reject_unknown(header, {"id", "version"}, "model")
    local_id = normalize_local_id(_string(header.get("id"), "model.id"), artifact="model")
    if local_id != model_root.name:
        raise ModelSpecError(
            f"model.id '{local_id}' does not match directory '{model_root.name}'"
        )
    version = header.get("version")
    if version is not None:
        version = _string(version, "model.version")

    fields = _mapping(raw.get("fields"), "fields")
    if not fields:
        raise ModelSpecError("fields must contain at least one field")
    schema: dict[str, ElementSpec] = {}
    for raw_name, raw_field in fields.items():
        field_name = raw_name.strip()
        if not field_name:
            raise ModelSpecError("model field name must not be empty")
        field = _mapping(raw_field, f"fields.{field_name}")
        _reject_unknown(field, {"type", "config"}, f"fields.{field_name}")
        type_name = _string(field.get("type"), f"fields.{field_name}.type")
        config = _mapping(field.get("config", {}), f"fields.{field_name}.config")
        schema[field_name] = ElementSpec(type_name, config)

    model_id = f"{normalized_module_id}/{local_id}"
    identity = f"dix:model:{model_id}@{version or ''}"
    definition = ModelDefinition(
        uid=uuid5(NAMESPACE_URL, identity),
        name=model_id,
        version=version,
        schema=schema,
    )
    return ModelArtifactDefinition(
        id=model_id,
        local_id=local_id,
        module_id=normalized_module_id,
        version=version,
        definition=definition,
        spec_path=spec_path,
    )


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ModelSpecError(f"{label} must be a table")
    return dict(value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelSpecError(f"{label} must be a non-empty string")
    return value.strip()


def _reject_unknown(value: Mapping[str, object], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ModelSpecError(f"unknown {label} key: {unknown[0]}")
