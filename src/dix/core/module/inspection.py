from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dix.core.application.spec import inspect_spec as inspect_application_spec
from dix.core.composition.spec import inspect_spec as inspect_composition_spec

from .errors import ModuleSpecError
from .models import ModuleInspection
from .validation import (
    IGNORED_DIRECTORY_NAMES,
    artifact_digest,
    canonical_directory,
    canonical_file,
    normalize_module_id,
    require_contained,
)


def inspect_module(root: Path, *, module_id: str) -> ModuleInspection:
    """Inspect all direct composition and application sources without importing code."""
    normalized_module_id = normalize_module_id(module_id)
    module_root = canonical_directory(root, label="module root")
    composition_definitions = _inspect_artifact_family(
        module_root,
        directory_name="compositions",
        spec_name="composition.toml",
        runtime_label="composition runtime",
        inspect_spec=inspect_composition_spec,
        module_id=normalized_module_id,
    )
    application_definitions = _inspect_artifact_family(
        module_root,
        directory_name="apps",
        spec_name="app.toml",
        runtime_label="application runtime",
        inspect_spec=inspect_application_spec,
        module_id=normalized_module_id,
    )
    if not composition_definitions and not application_definitions:
        raise ModuleSpecError(f"module contains no definitions: {module_root}")
    _require_unique_ids(composition_definitions, artifact="composition")
    _require_unique_ids(application_definitions, artifact="application")
    return ModuleInspection(
        id=normalized_module_id,
        root=module_root,
        artifact_digest=artifact_digest(module_root),
        composition_definitions=tuple(sorted(composition_definitions, key=lambda item: item.id)),
        application_definitions=tuple(sorted(application_definitions, key=lambda item: item.id)),
    )


def discover_modules(roots: Iterable[Path]) -> tuple[ModuleInspection, ...]:
    """Discover structurally bounded modules below trusted roots."""
    inspections: dict[str, ModuleInspection] = {}
    composition_ids: set[str] = set()
    application_ids: set[str] = set()
    for raw_root in roots:
        trusted_root = canonical_directory(raw_root, label="trusted module root")
        for module_root in _discover_module_roots(trusted_root, trusted_root):
            try:
                relative = module_root.relative_to(trusted_root)
            except ValueError as exc:
                raise ModuleSpecError(
                    f"module escapes trusted root '{trusted_root}': {module_root}"
                ) from exc
            if not relative.parts:
                raise ModuleSpecError(
                    "trusted root itself cannot be a module without an explicit module id: "
                    f"{trusted_root}"
                )
            module_id = normalize_module_id("/".join(relative.parts))
            if module_id in inspections:
                raise ModuleSpecError(f"duplicate module id across trusted roots: {module_id}")
            inspection = inspect_module(module_root, module_id=module_id)
            for definition in inspection.composition_definitions:
                if definition.id in composition_ids:
                    raise ModuleSpecError(
                        f"duplicate composition id across trusted roots: {definition.id}"
                    )
                composition_ids.add(definition.id)
            for definition in inspection.application_definitions:
                if definition.id in application_ids:
                    raise ModuleSpecError(
                        f"duplicate application id across trusted roots: {definition.id}"
                    )
                application_ids.add(definition.id)
            inspections[module_id] = inspection
    return tuple(inspections[item] for item in sorted(inspections))


def _inspect_artifact_family(
    module_root: Path,
    *,
    directory_name: str,
    spec_name: str,
    runtime_label: str,
    inspect_spec,
    module_id: str,
) -> list:
    family_root = module_root / directory_name
    if not family_root.exists():
        return []
    canonical_family_root = canonical_directory(
        family_root,
        root=module_root,
        label=f"{directory_name} directory",
    )
    definitions = []
    for source_dir in sorted(
        (item for item in canonical_family_root.iterdir() if item.is_dir()),
        key=lambda item: item.name,
    ):
        require_contained(source_dir, module_root, label=f"{directory_name} artifact directory")
        spec_path = canonical_file(
            source_dir / spec_name,
            root=module_root,
            label=spec_name.removesuffix(".toml") + " spec",
        )
        canonical_file(
            source_dir / "runtime.py",
            root=module_root,
            label=runtime_label,
        )
        definitions.append(inspect_spec(spec_path, module_id=module_id))
    return definitions


def _require_unique_ids(definitions: list, *, artifact: str) -> None:
    ids = [item.id for item in definitions]
    if len(ids) != len(set(ids)):
        duplicate = next(item for item in ids if ids.count(item) > 1)
        raise ModuleSpecError(f"duplicate {artifact} id: {duplicate}")


def _discover_module_roots(directory: Path, trusted_root: Path) -> tuple[Path, ...]:
    require_contained(directory, trusted_root, label="discovery directory")
    if (directory / "compositions").is_dir() or (directory / "apps").is_dir():
        for family in ("compositions", "apps"):
            if (directory / family).exists():
                canonical_directory(
                    directory / family,
                    root=trusted_root,
                    label=f"{family} directory",
                )
        return (directory.resolve(strict=True),)
    result: list[Path] = []
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if entry.name in IGNORED_DIRECTORY_NAMES:
            continue
        if entry.is_symlink():
            require_contained(entry, trusted_root, label="discovery symlink")
        if entry.is_dir():
            result.extend(_discover_module_roots(entry.resolve(strict=True), trusted_root))
    return tuple(result)
