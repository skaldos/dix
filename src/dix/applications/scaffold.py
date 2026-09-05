from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from dix.core.application.spec import normalize_effective_application_id, normalize_local_id
from dix.core.module.validation import normalize_local_id as normalize_artifact_local_id
from dix.core.module.validation import normalize_module_id


class ApplicationScaffoldError(Exception):
    """Raised when an application scaffold would be unsafe or ambiguous."""


def create_application_scaffold(
    module_root: Path,
    local_id: str,
    *,
    compositions: tuple[str, ...] = (),
    applications: tuple[str, ...] = (),
    exports: tuple[str, ...] = (),
    functions: tuple[str, ...] = (),
) -> Path:
    requested_module = module_root.expanduser()
    try:
        module = requested_module.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ApplicationScaffoldError(f"module path does not exist: {requested_module}") from exc
    if not module.is_dir():
        raise ApplicationScaffoldError(f"module path is not a directory: {module}")
    normalized_id = normalize_local_id(local_id)
    composition_map = _parse_assignments(compositions, "composition")
    application_map = _parse_assignments(applications, "app")
    collision = sorted(set(composition_map) & set(application_map))
    if collision:
        raise ApplicationScaffoldError(
            f"dependency alias is used by both composition and app: {collision[0]}"
        )
    dependencies = {**composition_map, **application_map}
    export_map = _parse_exports(exports, dependencies)
    local_functions = tuple(_validate_python_id(item, "function") for item in functions)
    effective = {item for values in export_map.values() for item in values}
    for function_id in local_functions:
        if function_id in effective:
            raise ApplicationScaffoldError(f"duplicate effective function name: {function_id}")
        if local_functions.count(function_id) > 1:
            raise ApplicationScaffoldError(f"duplicate function: {function_id}")
        effective.add(function_id)

    applications_root = module / "apps"
    target = applications_root / normalized_id
    if target.exists():
        raise ApplicationScaffoldError(f"application scaffold target already exists: {target}")
    payload = _render_spec(
        normalized_id,
        composition_map,
        application_map,
        export_map,
        local_functions,
    )
    applications_root.mkdir(exist_ok=True)
    applications_root = applications_root.resolve(strict=True)
    try:
        applications_root.relative_to(module)
    except ValueError as exc:
        raise ApplicationScaffoldError(
            f"apps directory escapes module root: {applications_root}"
        ) from exc
    temporary = Path(tempfile.mkdtemp(prefix=f".{normalized_id}.", dir=applications_root))
    try:
        (temporary / "app.toml").write_text(payload)
        temporary.rename(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target / "app.toml"


def _parse_assignments(values: tuple[str, ...], kind: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        alias, separator, raw_target = value.partition("=")
        alias = _validate_python_id(alias, f"{kind} alias")
        if not separator or not raw_target.strip():
            raise ApplicationScaffoldError(f"{kind} must use <alias>=<id>: {value}")
        if alias in result:
            raise ApplicationScaffoldError(f"duplicate {kind} alias: {alias}")
        target = raw_target.strip()
        if kind == "app":
            target = normalize_effective_application_id(target)
        else:
            module_id, slash, local_id = target.rpartition("/")
            if not slash:
                raise ApplicationScaffoldError(
                    f"composition target must be an effective id: {target}"
                )
            target = (
                f"{normalize_module_id(module_id)}/"
                f"{normalize_artifact_local_id(local_id, artifact='composition')}"
            )
        result[alias] = target
    return dict(sorted(result.items()))


def _parse_exports(values: tuple[str, ...], dependencies: dict[str, str]) -> dict[str, list[str]]:
    result = {alias: [] for alias in dependencies}
    effective: set[str] = set()
    for value in values:
        alias, dot, function_id = value.partition(".")
        alias = _validate_python_id(alias, "export alias")
        function_id = _validate_python_id(function_id, "export function") if dot else ""
        if not dot:
            raise ApplicationScaffoldError(f"export must use <alias>.<function>: {value}")
        if alias not in dependencies:
            raise ApplicationScaffoldError(f"export uses unknown dependency alias: {alias}")
        if function_id in effective:
            raise ApplicationScaffoldError(f"duplicate effective function name: {function_id}")
        effective.add(function_id)
        result[alias].append(function_id)
    return {alias: sorted(items) for alias, items in result.items()}


def _validate_python_id(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized.isidentifier() or normalized in {"context", "config"}:
        raise ApplicationScaffoldError(f"invalid {label}: {value!r}")
    return normalized


def _render_spec(
    local_id: str,
    compositions: dict[str, str],
    applications: dict[str, str],
    exports: dict[str, list[str]],
    functions: tuple[str, ...],
) -> str:
    lines = ["[app]", f"id = {json.dumps(local_id)}"]
    for table_name, dependencies in (
        ("compositions", compositions),
        ("apps", applications),
    ):
        for alias, target in dependencies.items():
            lines.extend(("", f"[{table_name}.{alias}]", f"use = {json.dumps(target)}"))
            if exports[alias]:
                values = ", ".join(json.dumps(item) for item in exports[alias])
                lines.append(f"export = [{values}]")
    for function_id in sorted(functions):
        lines.extend(
            (
                "",
                f"[functions.{function_id}]",
                f"description = {json.dumps(f'TODO: Describe {function_id}.')}",
            )
        )
    return "\n".join(lines) + "\n"
