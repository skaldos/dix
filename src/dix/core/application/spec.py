from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dix.core.composition.models import CompositionDependencySpec
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
    ApplicationDefinition,
    ApplicationDependencySpec,
    ApplicationFunctionSpec,
    ApplicationSource,
)

ApplicationSpecError = ModuleSpecError

_RESERVED_ALIASES = {"context", "config"}


def inspect_spec(path: Path, *, module_id: str) -> ApplicationDefinition:
    """Inspect one application source without importing its runtime module."""
    normalized_module_id = normalize_module_id(module_id)
    source = inspect_application_source(path)
    runtime_path = source.application_root / "runtime.py"
    canonical_file(runtime_path, root=source.module_root, label="application runtime")
    return ApplicationDefinition(
        id=f"{normalized_module_id}/{source.local_id}",
        local_id=source.local_id,
        module_id=normalized_module_id,
        module_root=source.module_root,
        application_root=source.application_root,
        spec_path=source.spec_path,
        runtime_path=runtime_path.resolve(strict=True),
        compositions=source.compositions,
        applications=source.applications,
        functions=source.functions,
    )


def inspect_application_source(path: Path) -> ApplicationSource:
    """Parse one unqualified app spec without requiring generated runtime code."""
    spec_path = canonical_file(path, label="application spec")
    if spec_path.name != "app.toml":
        raise ApplicationSpecError(f"application spec must be named app.toml: {spec_path}")
    application_root = spec_path.parent
    applications_root = application_root.parent
    module_root = applications_root.parent
    if applications_root.name != "apps":
        raise ApplicationSpecError(
            f"application spec must be directly below an apps directory: {spec_path}"
        )
    require_contained(application_root, module_root, label="application root")
    try:
        raw = tomllib.loads(spec_path.read_text())
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ApplicationSpecError(f"cannot read application spec {spec_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ApplicationSpecError(f"application spec must be a TOML table: {spec_path}")
    _reject_unknown_keys(raw, {"app", "compositions", "apps", "functions"}, "application spec")

    header = _require_mapping(raw.get("app"), "app")
    _reject_unknown_keys(header, {"id"}, "app")
    local_id = normalize_local_id(_require_string(header.get("id"), "app.id"))
    if local_id != application_root.name:
        raise ApplicationSpecError(
            f"app.id '{local_id}' does not match directory '{application_root.name}'"
        )

    compositions = _parse_dependencies(
        raw.get("compositions", {}),
        table_name="compositions",
        dependency_type="composition",
    )
    applications = _parse_dependencies(
        raw.get("apps", {}),
        table_name="apps",
        dependency_type="application",
    )
    shared_aliases = set(compositions) & set(applications)
    if shared_aliases:
        alias = min(shared_aliases)
        raise ApplicationSpecError(
            f"dependency alias is used by both compositions and apps: {alias}"
        )
    dependencies = {**compositions, **applications}
    functions = _parse_functions(raw.get("functions", {}), dependencies)
    _validate_function_names(compositions, applications, functions)
    return ApplicationSource(
        local_id=local_id,
        module_root=module_root,
        application_root=application_root,
        spec_path=spec_path,
        compositions=compositions,
        applications=applications,
        functions=functions,
    )


def normalize_local_id(local_id: str) -> str:
    return normalize_artifact_local_id(local_id, artifact="application")


def normalize_effective_application_id(application_id: str) -> str:
    parts = application_id.rsplit("/", 1)
    if len(parts) != 2:
        raise ApplicationSpecError(
            f"application dependency must use an effective id: {application_id!r}"
        )
    return f"{normalize_module_id(parts[0])}/{normalize_local_id(parts[1])}"


def _parse_dependencies(
    raw: object,
    *,
    table_name: str,
    dependency_type: str,
) -> dict[str, CompositionDependencySpec] | dict[str, ApplicationDependencySpec]:
    table = _require_mapping(raw, table_name)
    result: dict[str, CompositionDependencySpec | ApplicationDependencySpec] = {}
    for alias, raw_dependency in table.items():
        _validate_alias(alias, f"{dependency_type} alias")
        label = f"{table_name}.{alias}"
        dependency = _require_mapping(raw_dependency, label)
        _reject_unknown_keys(dependency, {"use", "config", "export"}, label)
        raw_use = _require_string(dependency.get("use"), f"{label}.use")
        use = (
            _normalize_effective_composition_id(raw_use)
            if dependency_type == "composition"
            else normalize_effective_application_id(raw_use)
        )
        config = _require_mapping(dependency.get("config", {}), f"{label}.config")
        exports = _parse_exports(dependency.get("export", []), label)
        dependency_class = (
            CompositionDependencySpec
            if dependency_type == "composition"
            else ApplicationDependencySpec
        )
        result[alias] = dependency_class(use=use, config=config, export=exports)
    return dict(sorted(result.items()))


def _parse_exports(raw: object, label: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ApplicationSpecError(f"{label}.export must be a list of strings")
    exports: list[str] = []
    for raw_export in raw:
        function_id = _validate_function_id(raw_export, f"{label}.export")
        if function_id in exports:
            raise ApplicationSpecError(
                f"duplicate export from dependency alias '{label.rsplit('.', 1)[-1]}': "
                f"{function_id}"
            )
        exports.append(function_id)
    return tuple(exports)


def _parse_functions(
    raw: object,
    dependencies: Mapping[str, CompositionDependencySpec | ApplicationDependencySpec],
) -> dict[str, ApplicationFunctionSpec]:
    table = _require_mapping(raw, "functions")
    result: dict[str, ApplicationFunctionSpec] = {}
    for function_id, raw_function in table.items():
        _validate_function_id(function_id, "function id")
        value = _require_mapping(raw_function, f"functions.{function_id}")
        _reject_unknown_keys(value, {"description", "export"}, f"functions.{function_id}")
        description = value.get("description")
        if description is not None:
            description = _require_string(description, f"functions.{function_id}.description")
        origin = value.get("export")
        if origin is not None:
            origin = _require_string(origin, f"functions.{function_id}.export")
            parts = origin.split(".")
            if len(parts) != 2 or parts[0] not in dependencies:
                raise ApplicationSpecError(
                    f"functions.{function_id}.export must reference a declared dependency alias"
                )
            _validate_function_id(parts[1], f"functions.{function_id}.export")
        result[function_id] = ApplicationFunctionSpec(
            description=description,
            export=origin,
        )
    return dict(sorted(result.items()))


def _validate_function_names(
    compositions: Mapping[str, CompositionDependencySpec],
    applications: Mapping[str, ApplicationDependencySpec],
    functions: Mapping[str, ApplicationFunctionSpec],
) -> None:
    owners: dict[str, str] = {}
    for table_name, dependencies in (
        ("compositions", compositions),
        ("apps", applications),
    ):
        for alias, dependency in dependencies.items():
            for function_id in dependency.export:
                owner = f"{table_name}.{alias}.export"
                previous = owners.setdefault(function_id, owner)
                if previous != owner:
                    raise ApplicationSpecError(
                        f"duplicate effective function '{function_id}' from {previous} and {owner}"
                    )
    for function_id in functions:
        if function_id in owners:
            raise ApplicationSpecError(
                f"duplicate effective function '{function_id}' from {owners[function_id]} "
                f"and functions.{function_id}"
            )
        owners[function_id] = f"functions.{function_id}"


def _normalize_effective_composition_id(composition_id: str) -> str:
    parts = composition_id.rsplit("/", 1)
    if len(parts) != 2:
        raise ApplicationSpecError(
            f"composition dependency must use an effective id: {composition_id!r}"
        )
    local_id = normalize_artifact_local_id(parts[1], artifact="composition")
    return f"{normalize_module_id(parts[0])}/{local_id}"


def _validate_alias(alias: object, label: str) -> str:
    if not isinstance(alias, str) or not alias.isidentifier() or alias in _RESERVED_ALIASES:
        raise ApplicationSpecError(f"invalid {label}: {alias!r}")
    return alias


def _validate_function_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.isidentifier():
        raise ApplicationSpecError(f"invalid {label}: {value!r}")
    return value


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ApplicationSpecError(f"{label} must be a TOML table")
    return value


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApplicationSpecError(f"{label} must be a non-empty string")
    return value.strip()


def _reject_unknown_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ApplicationSpecError(f"unknown key in {label}: {unknown[0]}")
