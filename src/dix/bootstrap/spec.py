from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dix.core import ModuleComponent, create_core_component_registry
from dix.core.application import normalize_effective_application_id
from dix.core.module import ModuleSpecError, normalize_module_id

from .models import LauncherDefinition, LauncherModule


class LauncherSpecError(ValueError):
    """Raised when a launcher specification is structurally invalid."""


def load_launcher_spec(path: Path) -> LauncherDefinition:
    """Read, normalize, and structurally inspect one launcher v1 specification."""
    spec_path = _canonical_file(path, "launcher spec")
    try:
        raw = tomllib.loads(spec_path.read_text())
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise LauncherSpecError(f"cannot read launcher spec {spec_path}: {exc}") from exc

    _reject_unknown_keys(raw, {"launcher", "modules"}, "launcher spec")
    launcher = _require_mapping(raw.get("launcher"), "launcher")
    _reject_unknown_keys(
        launcher,
        {"name", "adapter", "application", "function"},
        "launcher",
    )

    name = _require_string(launcher.get("name"), "launcher.name")
    adapter = _require_string(launcher.get("adapter"), "launcher.adapter")
    if adapter != "python_cli":
        raise LauncherSpecError(f"unknown launcher adapter: {adapter}")
    try:
        application = normalize_effective_application_id(
            _require_string(launcher.get("application"), "launcher.application")
        )
    except ModuleSpecError as exc:
        raise LauncherSpecError(f"invalid launcher.application: {exc}") from exc
    function = _require_string(launcher.get("function"), "launcher.function")
    if not function.isidentifier():
        raise LauncherSpecError(f"launcher.function must be a Python identifier: {function!r}")

    raw_modules = raw.get("modules")
    if not isinstance(raw_modules, list) or not raw_modules:
        raise LauncherSpecError("modules must be a non-empty TOML array of tables")

    modules: list[LauncherModule] = []
    module_ids: set[str] = set()
    applications: set[str] = set()
    registry = create_core_component_registry()
    module_component = registry.require("module", ModuleComponent)
    for index, raw_module in enumerate(raw_modules):
        label = f"modules[{index}]"
        module = _require_mapping(raw_module, label)
        _reject_unknown_keys(module, {"id", "source"}, label)
        try:
            module_id = normalize_module_id(_require_string(module.get("id"), f"{label}.id"))
        except ModuleSpecError as exc:
            raise LauncherSpecError(f"invalid {label}.id: {exc}") from exc
        if module_id in module_ids:
            raise LauncherSpecError(f"duplicate module id: {module_id}")
        source_value = _require_string(module.get("source"), f"{label}.source")
        source = Path(source_value).expanduser()
        if not source.is_absolute():
            source = spec_path.parent / source
        source = _canonical_directory(source, f"{label}.source")
        try:
            inspection = module_component.inspect_module(source, module_id=module_id)
        except Exception as exc:
            raise LauncherSpecError(
                f"cannot inspect {label} '{module_id}' at {source}: {exc}"
            ) from exc
        module_ids.add(module_id)
        applications.update(item.id for item in inspection.application_definitions)
        modules.append(LauncherModule(id=module_id, source=source))

    if application not in applications:
        raise LauncherSpecError(
            f"launcher application is not provided by the configured modules: {application}"
        )

    return LauncherDefinition(
        name=name,
        adapter=adapter,
        application=application,
        function=function,
        modules=tuple(modules),
        spec_path=spec_path,
    )


def _canonical_file(path: Path, label: str) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise LauncherSpecError(f"{label} does not exist: {path}") from exc
    if not resolved.is_file():
        raise LauncherSpecError(f"{label} is not a file: {resolved}")
    return resolved


def _canonical_directory(path: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise LauncherSpecError(f"{label} does not exist: {path}") from exc
    if not resolved.is_dir():
        raise LauncherSpecError(f"{label} is not a directory: {resolved}")
    return resolved


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LauncherSpecError(f"{label} must be a TOML table")
    return value


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LauncherSpecError(f"{label} must be a non-empty string")
    return value.strip()


def _reject_unknown_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise LauncherSpecError(f"unknown key in {label}: {unknown[0]}")
