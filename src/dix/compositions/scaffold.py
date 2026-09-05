from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dix.core.composition import normalize_local_id, normalize_module_id


class CompositionScaffoldError(Exception):
    """Raised when a module or composition scaffold would be unsafe or ambiguous."""


@dataclass(frozen=True)
class ExportRequest:
    dependency_alias: str
    function_id: str
    local_id: str


def create_module_scaffold(root: Path, module_id: str) -> Path:
    normalized_id = normalize_module_id(module_id)
    scaffold_root = root.expanduser().resolve()
    target = scaffold_root.joinpath(*normalized_id.split("/"))
    if target.exists():
        raise CompositionScaffoldError(f"module scaffold target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    canonical_parent = target.parent.resolve(strict=True)
    if scaffold_root.exists():
        try:
            canonical_parent.relative_to(scaffold_root.resolve(strict=True))
        except ValueError as exc:
            raise CompositionScaffoldError(
                f"module scaffold target escapes root '{scaffold_root}': {target}"
            ) from exc
    (target / "compositions").mkdir(parents=True)
    (target / "apps").mkdir()
    return target


def create_composition_scaffold(
    module_root: Path,
    local_id: str,
    *,
    components: tuple[str, ...] = (),
    compositions: tuple[str, ...] = (),
    exports: tuple[str, ...] = (),
    functions: tuple[str, ...] = (),
) -> Path:
    module = module_root.expanduser().resolve(strict=True)
    compositions_root = (module / "compositions").resolve(strict=True)
    try:
        compositions_root.relative_to(module)
    except ValueError as exc:
        raise CompositionScaffoldError(
            f"compositions directory escapes module root: {compositions_root}"
        ) from exc
    normalized_id = normalize_local_id(local_id)
    component_map = _parse_assignments(components, "component")
    composition_map = _parse_assignments(compositions, "composition")
    collision = sorted(set(component_map) & set(composition_map))
    if collision:
        raise CompositionScaffoldError(
            f"dependency alias is used by both component and composition: {collision[0]}"
        )
    export_requests = tuple(_parse_export(item, composition_map) for item in exports)
    local_functions = tuple(_validate_python_id(item, "function") for item in functions)
    effective_names: set[str] = set()
    for request in export_requests:
        if request.local_id in effective_names:
            raise CompositionScaffoldError(
                f"duplicate effective function name: {request.local_id}"
            )
        effective_names.add(request.local_id)
    for function_id in local_functions:
        if function_id in effective_names:
            raise CompositionScaffoldError(
                f"duplicate effective function name: {function_id}"
            )
        effective_names.add(function_id)

    target = compositions_root / normalized_id
    if target.exists():
        raise CompositionScaffoldError(
            f"composition scaffold target already exists: {target}"
        )
    payload = _render_spec(
        normalized_id,
        component_map,
        composition_map,
        export_requests,
        local_functions,
    )
    temporary = Path(tempfile.mkdtemp(prefix=f".{normalized_id}.", dir=compositions_root))
    try:
        (temporary / "composition.toml").write_text(payload)
        temporary.rename(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target / "composition.toml"


def _parse_assignments(values: tuple[str, ...], label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        alias, separator, target = value.partition("=")
        alias = _validate_python_id(alias, f"{label} alias")
        if not separator or not target.strip():
            raise CompositionScaffoldError(f"{label} must use <alias>=<id>: {value}")
        if alias in result:
            raise CompositionScaffoldError(f"duplicate {label} alias: {alias}")
        target = target.strip()
        if label == "composition":
            module_id, slash, local_id = target.rpartition("/")
            if not slash:
                raise CompositionScaffoldError(
                    f"composition target must be an effective id: {target}"
                )
            target = f"{normalize_module_id(module_id)}/{normalize_local_id(local_id)}"
        result[alias] = target
    return dict(sorted(result.items()))


def _parse_export(value: str, compositions: dict[str, str]) -> ExportRequest:
    origin, separator, local = value.partition("=")
    alias, dot, function_id = origin.partition(".")
    if not dot:
        raise CompositionScaffoldError(
            f"export must use <alias>.<function>[=<local-name>]: {value}"
        )
    alias = _validate_python_id(alias, "export alias")
    function_id = _validate_python_id(function_id, "export function")
    local_id = _validate_python_id(local if separator else function_id, "local function")
    if alias not in compositions:
        raise CompositionScaffoldError(f"export uses unknown composition alias: {alias}")
    return ExportRequest(alias, function_id, local_id)


def _validate_python_id(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized.isidentifier() or normalized in {"context", "config"}:
        raise CompositionScaffoldError(f"invalid {label}: {value!r}")
    return normalized


def _render_spec(
    local_id: str,
    components: dict[str, str],
    compositions: dict[str, str],
    exports: tuple[ExportRequest, ...],
    functions: tuple[str, ...],
) -> str:
    lines = ["[composition]", f"id = {json.dumps(local_id)}"]
    if components:
        lines.extend(("", "[components]"))
        lines.extend(f"{alias} = {json.dumps(target)}" for alias, target in components.items())
    direct_exports: dict[str, list[str]] = {alias: [] for alias in compositions}
    alias_exports: list[ExportRequest] = []
    for request in exports:
        if request.local_id == request.function_id:
            direct_exports[request.dependency_alias].append(request.function_id)
        else:
            alias_exports.append(request)
    for alias, target in compositions.items():
        lines.extend(("", f"[compositions.{alias}]", f"use = {json.dumps(target)}"))
        if direct_exports[alias]:
            values = ", ".join(json.dumps(item) for item in direct_exports[alias])
            lines.append(f"export = [{values}]")
    for request in alias_exports:
        lines.extend(
            (
                "",
                f"[functions.{request.local_id}]",
                f"export = {json.dumps(f'{request.dependency_alias}.{request.function_id}')}",
                f"description = {json.dumps(f'TODO: Describe {request.local_id}.')}",
            )
        )
    for function_id in functions:
        lines.extend(
            (
                "",
                f"[functions.{function_id}]",
                f"description = {json.dumps(f'TODO: Describe {function_id}.')}",
            )
        )
    return "\n".join(lines) + "\n"
