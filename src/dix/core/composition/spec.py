from __future__ import annotations

import hashlib
import os
import re
import tomllib
from pathlib import Path
from collections.abc import Iterable
from typing import Any, Mapping

from .models import (
    CompositionDefinition,
    CompositionDependencySpec,
    CompositionFunctionSpec,
    ModuleInspection,
)

_ID_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_IGNORED_DIRECTORY_NAMES = {".git", ".pytest_cache", "__pycache__"}
_IGNORED_FILE_SUFFIXES = {".pyc", ".pyo"}
_RESERVED_ALIASES = {"context", "config"}
_RESERVED_FUNCTIONS = {"start", "stop"}


class CompositionSpecError(Exception):
    """Raised when a composition source or module structure is invalid."""


def inspect_spec(path: Path, *, module_id: str) -> CompositionDefinition:
    """Inspect one composition source without importing its runtime module."""
    normalized_module_id = normalize_module_id(module_id)
    spec_path = _canonical_file(path, label="composition spec")
    if spec_path.name != "composition.toml":
        raise CompositionSpecError(f"composition spec must be named composition.toml: {spec_path}")
    composition_root = spec_path.parent
    compositions_root = composition_root.parent
    module_root = compositions_root.parent
    if compositions_root.name != "compositions":
        raise CompositionSpecError(
            f"composition spec must be directly below a compositions directory: {spec_path}"
        )
    _require_contained(composition_root, module_root, label="composition root")
    runtime_path = composition_root / "runtime.py"
    _canonical_file(runtime_path, root=module_root, label="composition runtime")

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
    local_id = _require_string(header.get("id"), "composition.id")
    normalize_local_id(local_id)
    if local_id != composition_root.name:
        raise CompositionSpecError(
            f"composition.id '{local_id}' does not match directory '{composition_root.name}'"
        )

    components = _parse_components(raw.get("components", {}))
    compositions = _parse_compositions(raw.get("compositions", {}))
    shared_aliases = set(components) & set(compositions)
    if shared_aliases:
        alias = sorted(shared_aliases)[0]
        raise CompositionSpecError(
            f"dependency alias is used by both components and compositions: {alias}"
        )
    functions = _parse_functions(raw.get("functions", {}), compositions)
    _validate_function_names(compositions, functions)

    return CompositionDefinition(
        id=f"{normalized_module_id}/{local_id}",
        local_id=local_id,
        module_id=normalized_module_id,
        module_root=module_root,
        composition_root=composition_root,
        spec_path=spec_path,
        runtime_path=runtime_path.resolve(strict=True),
        components=components,
        compositions=compositions,
        functions=functions,
    )


def inspect_module(root: Path, *, module_id: str) -> ModuleInspection:
    """Inspect all direct composition sources in one module without importing code."""
    normalized_module_id = normalize_module_id(module_id)
    module_root = _canonical_directory(root, label="module root")
    compositions_root = module_root / "compositions"
    _canonical_directory(compositions_root, root=module_root, label="compositions directory")

    composition_dirs = sorted(
        (item for item in compositions_root.iterdir() if item.is_dir()),
        key=lambda item: item.name,
    )
    if not composition_dirs:
        raise CompositionSpecError(f"module contains no compositions: {module_root}")
    definitions: list[CompositionDefinition] = []
    for source_dir in composition_dirs:
        _require_contained(source_dir, module_root, label="composition directory")
        _canonical_file(
            source_dir / "composition.toml",
            root=module_root,
            label="composition spec",
        )
        _canonical_file(
            source_dir / "runtime.py",
            root=module_root,
            label="composition runtime",
        )
        definitions.append(
            inspect_spec(source_dir / "composition.toml", module_id=normalized_module_id)
        )
    ids = [item.id for item in definitions]
    if len(ids) != len(set(ids)):
        duplicate = next(item for item in ids if ids.count(item) > 1)
        raise CompositionSpecError(f"duplicate composition id: {duplicate}")
    return ModuleInspection(
        id=normalized_module_id,
        root=module_root,
        artifact_digest=_artifact_digest(module_root),
        definitions=tuple(sorted(definitions, key=lambda item: item.id)),
    )


def discover_modules(roots: Iterable[Path]) -> tuple[ModuleInspection, ...]:
    """Discover structurally bounded modules below trusted roots."""
    inspections: dict[str, ModuleInspection] = {}
    for raw_root in roots:
        trusted_root = _canonical_directory(raw_root, label="trusted module root")
        for module_root in _discover_module_roots(trusted_root, trusted_root):
            try:
                relative = module_root.relative_to(trusted_root)
            except ValueError as exc:
                raise CompositionSpecError(
                    f"module escapes trusted root '{trusted_root}': {module_root}"
                ) from exc
            if not relative.parts:
                raise CompositionSpecError(
                    f"trusted root itself cannot be a module without an explicit module id: {trusted_root}"
                )
            module_id = normalize_module_id("/".join(relative.parts))
            if module_id in inspections:
                raise CompositionSpecError(f"duplicate module id across trusted roots: {module_id}")
            inspection = inspect_module(module_root, module_id=module_id)
            for definition in inspection.definitions:
                for existing in inspections.values():
                    if any(item.id == definition.id for item in existing.definitions):
                        raise CompositionSpecError(
                            f"duplicate composition id across trusted roots: {definition.id}"
                        )
            inspections[module_id] = inspection
    return tuple(inspections[item] for item in sorted(inspections))


def normalize_module_id(module_id: str) -> str:
    if not isinstance(module_id, str):
        raise CompositionSpecError("module id must be a string")
    value = module_id.strip().replace("\\", "/")
    parts = value.split("/")
    if not value or value.startswith("/") or any(
        not part or part in {".", ".."} or not _ID_SEGMENT.fullmatch(part)
        for part in parts
    ):
        raise CompositionSpecError(f"invalid module id: {module_id!r}")
    return "/".join(parts)


def normalize_local_id(local_id: str) -> str:
    if not isinstance(local_id, str):
        raise CompositionSpecError("local composition id must be a string")
    value = local_id.strip()
    if not _ID_SEGMENT.fullmatch(value):
        raise CompositionSpecError(f"invalid local composition id: {local_id!r}")
    return value


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
        _reject_unknown_keys(dependency, {"use", "config", "export"}, f"compositions.{alias}")
        use = normalize_effective_composition_id(
            _require_string(dependency.get("use"), f"compositions.{alias}.use")
        )
        config = _require_mapping(dependency.get("config", {}), f"compositions.{alias}.config")
        raw_exports = dependency.get("export", [])
        if not isinstance(raw_exports, list) or not all(
            isinstance(item, str) for item in raw_exports
        ):
            raise CompositionSpecError(f"compositions.{alias}.export must be a list of strings")
        exports: list[str] = []
        for raw_export in raw_exports:
            function_id = _validate_function_id(raw_export, f"compositions.{alias}.export")
            if function_id == "*":
                raise CompositionSpecError("composition exports must be concrete; '*' is not allowed")
            if function_id in exports:
                raise CompositionSpecError(
                    f"duplicate export from composition alias '{alias}': {function_id}"
                )
            exports.append(function_id)
        result[alias] = CompositionDependencySpec(
            use=use,
            config=config,
            export=tuple(exports),
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
        _reject_unknown_keys(value, {"description", "export"}, f"functions.{function_id}")
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
            description=description,
            export=origin,
        )
    return dict(sorted(result.items()))


def _validate_function_names(
    compositions: Mapping[str, CompositionDependencySpec],
    functions: Mapping[str, CompositionFunctionSpec],
) -> None:
    owners: dict[str, str] = {}
    for alias, dependency in compositions.items():
        for function_id in dependency.export:
            previous = owners.setdefault(function_id, f"compositions.{alias}.export")
            if previous != f"compositions.{alias}.export":
                raise CompositionSpecError(
                    f"duplicate effective function '{function_id}' from {previous} and "
                    f"compositions.{alias}.export"
                )
    for function_id in functions:
        if function_id in owners:
            raise CompositionSpecError(
                f"duplicate effective function '{function_id}' from {owners[function_id]} "
                f"and functions.{function_id}"
            )
        owners[function_id] = f"functions.{function_id}"


def normalize_effective_composition_id(composition_id: str) -> str:
    parts = composition_id.rsplit("/", 1)
    if len(parts) != 2:
        raise CompositionSpecError(
            f"composition dependency must use an effective id: {composition_id!r}"
        )
    module_id = normalize_module_id(parts[0])
    local_id = normalize_local_id(parts[1])
    return f"{module_id}/{local_id}"


def _validate_alias(alias: object, label: str) -> str:
    if not isinstance(alias, str) or not alias.isidentifier() or alias in _RESERVED_ALIASES:
        raise CompositionSpecError(f"invalid {label}: {alias!r}")
    return alias


def _validate_function_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.isidentifier() or value in _RESERVED_FUNCTIONS:
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


def _reject_unknown_keys(
    value: Mapping[str, Any],
    allowed: set[str],
    label: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CompositionSpecError(f"unknown key in {label}: {unknown[0]}")


def _canonical_file(path: Path, *, root: Path | None = None, label: str) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise CompositionSpecError(f"{label} does not exist: {path}") from exc
    if not resolved.is_file():
        raise CompositionSpecError(f"{label} is not a file: {resolved}")
    if root is not None:
        _require_contained(resolved, root, label=label)
    return resolved


def _canonical_directory(path: Path, *, root: Path | None = None, label: str) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise CompositionSpecError(f"{label} does not exist: {path}") from exc
    if not resolved.is_dir():
        raise CompositionSpecError(f"{label} is not a directory: {resolved}")
    if root is not None:
        _require_contained(resolved, root, label=label)
    return resolved


def _require_contained(path: Path, root: Path, *, label: str) -> None:
    canonical_root = root.resolve(strict=True)
    try:
        path.resolve(strict=True).relative_to(canonical_root)
    except (OSError, ValueError) as exc:
        raise CompositionSpecError(f"{label} escapes root '{canonical_root}': {path}") from exc


def _discover_module_roots(directory: Path, trusted_root: Path) -> tuple[Path, ...]:
    _require_contained(directory, trusted_root, label="discovery directory")
    if (directory / "compositions").is_dir():
        _require_contained(directory / "compositions", trusted_root, label="compositions directory")
        return (directory.resolve(strict=True),)
    result: list[Path] = []
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if entry.name in _IGNORED_DIRECTORY_NAMES:
            continue
        if entry.is_symlink():
            _require_contained(entry, trusted_root, label="discovery symlink")
        if entry.is_dir():
            result.extend(_discover_module_roots(entry.resolve(strict=True), trusted_root))
    return tuple(result)


def _artifact_digest(module_root: Path) -> str:
    """Hash stable relative paths and bytes, excluding Python/cache runtime artifacts."""
    digest = hashlib.sha256()
    visited_directories: set[Path] = set()
    for current, directory_names, file_names in os.walk(module_root, followlinks=True):
        canonical_current = Path(current).resolve(strict=True)
        _require_contained(canonical_current, module_root, label="module artifact directory")
        if canonical_current in visited_directories:
            raise CompositionSpecError(
                f"module artifact directory is reachable more than once: {current}"
            )
        visited_directories.add(canonical_current)
        directory_names[:] = sorted(
            name for name in directory_names if name not in _IGNORED_DIRECTORY_NAMES
        )
        current_path = Path(current)
        for name in directory_names:
            _require_contained(
                current_path / name,
                module_root,
                label="module artifact directory",
            )
        for name in sorted(file_names):
            path = current_path / name
            if path.suffix in _IGNORED_FILE_SUFFIXES:
                continue
            _require_contained(path, module_root, label="module artifact")
            relative = path.relative_to(module_root).as_posix().encode()
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            try:
                payload = path.read_bytes()
            except OSError as exc:
                raise CompositionSpecError(f"cannot read module artifact {path}: {exc}") from exc
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
    return digest.hexdigest()
