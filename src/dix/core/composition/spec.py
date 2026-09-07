from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dix.core.contract import ContractReference
from dix.core.module.errors import ModuleSpecError
from dix.core.module.validation import (
    canonical_file,
    normalize_module_id,
    require_contained,
)
from dix.core.module.validation import (
    normalize_local_id as normalize_artifact_local_id,
)

from .models import (
    CompositionDefinition,
    CompositionDependencySpec,
    CompositionFunctionSpec,
    CompositionSource,
)

CompositionSpecError = ModuleSpecError

_RESERVED_ALIASES = {"context", "config"}


def inspect_spec(path: Path, *, module_id: str) -> CompositionDefinition:
    """Inspect one composition source without importing its runtime module."""
    normalized_module_id = normalize_module_id(module_id)
    source = inspect_composition_source(path)
    runtime_path = source.composition_root / "runtime.py"
    canonical_file(runtime_path, root=source.module_root, label="composition runtime")
    return CompositionDefinition(
        id=f"{normalized_module_id}/{source.local_id}",
        local_id=source.local_id,
        module_id=normalized_module_id,
        module_root=source.module_root,
        composition_root=source.composition_root,
        spec_path=source.spec_path,
        runtime_path=runtime_path.resolve(strict=True),
        components=source.components,
        compositions=source.compositions,
        functions=source.functions,
    )


def inspect_composition_source(path: Path) -> CompositionSource:
    """Parse one unqualified source spec without requiring generated runtime code."""
    spec_path = canonical_file(path, label="composition spec")
    if spec_path.name != "composition.toml":
        raise CompositionSpecError(f"composition spec must be named composition.toml: {spec_path}")
    composition_root = spec_path.parent
    compositions_root = composition_root.parent
    module_root = compositions_root.parent
    if compositions_root.name != "compositions":
        raise CompositionSpecError(
            f"composition spec must be directly below a compositions directory: {spec_path}"
        )
    require_contained(composition_root, module_root, label="composition root")
    try:
        raw = tomllib.loads(spec_path.read_text())
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise CompositionSpecError(f"cannot read composition spec {spec_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise CompositionSpecError(f"composition spec must be a TOML table: {spec_path}")
    allowed_top = {"composition", "components", "compositions", "functions"}
    _reject_unknown_keys(raw, allowed_top, "composition spec")

    header = _require_mapping(raw.get("composition"), "composition")
    _reject_unknown_keys(header, {"id"}, "composition")
    local_id = normalize_local_id(_require_string(header.get("id"), "composition.id"))
    if local_id != composition_root.name:
        raise CompositionSpecError(
            f"composition.id '{local_id}' does not match directory '{composition_root.name}'"
        )

    components = _parse_components(raw.get("components", {}))
    compositions = _parse_compositions(raw.get("compositions", {}))
    shared_aliases = set(components) & set(compositions)
    if shared_aliases:
        alias = min(shared_aliases)
        raise CompositionSpecError(
            f"dependency alias is used by both components and compositions: {alias}"
        )
    functions = _parse_functions(raw.get("functions", {}), compositions)

    return CompositionSource(
        local_id=local_id,
        module_root=module_root,
        composition_root=composition_root,
        spec_path=spec_path,
        components=components,
        compositions=compositions,
        functions=functions,
    )


def normalize_local_id(local_id: str) -> str:
    return normalize_artifact_local_id(local_id, artifact="composition")


def normalize_effective_composition_id(composition_id: str) -> str:
    parts = composition_id.rsplit("/", 1)
    if len(parts) != 2:
        raise CompositionSpecError(
            f"composition dependency must use an effective id: {composition_id!r}"
        )
    module_id = normalize_module_id(parts[0])
    local_id = normalize_local_id(parts[1])
    return f"{module_id}/{local_id}"


def _parse_components(raw: object) -> dict[str, str]:
    table = _require_mapping(raw, "components")
    result: dict[str, str] = {}
    for alias, component_id in table.items():
        _validate_alias(alias, "component alias")
        result[alias] = _require_string(component_id, f"components.{alias}")
    return dict(sorted(result.items()))


def _parse_compositions(raw: object) -> dict[str, CompositionDependencySpec]:
    table = _require_mapping(raw, "compositions")
    result: dict[str, CompositionDependencySpec] = {}
    for alias, raw_dependency in table.items():
        _validate_alias(alias, "composition alias")
        dependency = _require_mapping(raw_dependency, f"compositions.{alias}")
        _reject_unknown_keys(dependency, {"use", "config"}, f"compositions.{alias}")
        use = normalize_effective_composition_id(
            _require_string(dependency.get("use"), f"compositions.{alias}.use")
        )
        config = _require_mapping(dependency.get("config", {}), f"compositions.{alias}.config")
        result[alias] = CompositionDependencySpec(
            use=use,
            config=config,
        )
    return dict(sorted(result.items()))


def _parse_functions(
    raw: object,
    compositions: Mapping[str, CompositionDependencySpec],
) -> dict[str, CompositionFunctionSpec]:
    table = _require_mapping(raw, "functions")
    result: dict[str, CompositionFunctionSpec] = {}
    for function_id, raw_function in table.items():
        _validate_function_id(function_id, "function id")
        value = _require_mapping(raw_function, f"functions.{function_id}")
        _reject_unknown_keys(
            value, {"contract", "description", "export"}, f"functions.{function_id}"
        )
        contract = _parse_contract_reference(
            value.get("contract"), f"functions.{function_id}.contract"
        )
        description = value.get("description")
        if description is not None:
            description = _require_string(description, f"functions.{function_id}.description")
        origin = value.get("export")
        if origin is not None:
            origin = _require_string(origin, f"functions.{function_id}.export")
            parts = origin.split(".")
            if len(parts) != 2 or parts[0] not in compositions:
                raise CompositionSpecError(
                    f"functions.{function_id}.export must reference a declared composition alias"
                )
            _validate_function_id(parts[1], f"functions.{function_id}.export")
        result[function_id] = CompositionFunctionSpec(
            contract=contract,
            description=description,
            export=origin,
        )
    return dict(sorted(result.items()))


def _parse_contract_reference(raw: object, label: str) -> ContractReference:
    value = _require_mapping(raw, label)
    _reject_unknown_keys(value, {"use", "version"}, label)
    use = _require_string(value.get("use"), f"{label}.use")
    version = value.get("version")
    if version is not None:
        version = _require_string(version, f"{label}.version")
    try:
        return ContractReference(use=use, version=version)
    except ValueError as exc:
        raise CompositionSpecError(f"invalid {label}: {exc}") from exc


def _validate_alias(alias: object, label: str) -> str:
    if not isinstance(alias, str) or not alias.isidentifier() or alias in _RESERVED_ALIASES:
        raise CompositionSpecError(f"invalid {label}: {alias!r}")
    return alias


def _validate_function_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.isidentifier():
        raise CompositionSpecError(f"invalid {label}: {value!r}")
    return value


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CompositionSpecError(f"{label} must be a TOML table")
    return value


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CompositionSpecError(f"{label} must be a non-empty string")
    return value.strip()


def _reject_unknown_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CompositionSpecError(f"unknown key in {label}: {unknown[0]}")
