from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from .errors import ModuleSpecError

ID_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
IGNORED_DIRECTORY_NAMES = {".git", ".pytest_cache", "__pycache__"}
IGNORED_FILE_SUFFIXES = {".pyc", ".pyo"}


def normalize_module_id(module_id: str) -> str:
    if not isinstance(module_id, str):
        raise ModuleSpecError("module id must be a string")
    value = module_id.strip().replace("\\", "/")
    parts = value.split("/")
    if not value or value.startswith("/") or any(
        not part or part in {".", ".."} or not ID_SEGMENT.fullmatch(part)
        for part in parts
    ):
        raise ModuleSpecError(f"invalid module id: {module_id!r}")
    return "/".join(parts)


def normalize_local_id(local_id: str, *, artifact: str) -> str:
    if not isinstance(local_id, str):
        raise ModuleSpecError(f"local {artifact} id must be a string")
    value = local_id.strip()
    if not ID_SEGMENT.fullmatch(value):
        raise ModuleSpecError(f"invalid local {artifact} id: {local_id!r}")
    return value


def canonical_file(path: Path, *, root: Path | None = None, label: str) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ModuleSpecError(f"{label} does not exist: {path}") from exc
    if not resolved.is_file():
        raise ModuleSpecError(f"{label} is not a file: {resolved}")
    if root is not None:
        require_contained(resolved, root, label=label)
    return resolved


def canonical_directory(path: Path, *, root: Path | None = None, label: str) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ModuleSpecError(f"{label} does not exist: {path}") from exc
    if not resolved.is_dir():
        raise ModuleSpecError(f"{label} is not a directory: {resolved}")
    if root is not None:
        require_contained(resolved, root, label=label)
    return resolved


def require_contained(path: Path, root: Path, *, label: str) -> None:
    canonical_root = root.resolve(strict=True)
    try:
        path.resolve(strict=True).relative_to(canonical_root)
    except (OSError, ValueError) as exc:
        raise ModuleSpecError(f"{label} escapes root '{canonical_root}': {path}") from exc


def artifact_digest(module_root: Path) -> str:
    """Hash stable relative paths and bytes, excluding Python/cache runtime artifacts."""
    digest = hashlib.sha256()
    visited_directories: set[Path] = set()
    for current, directory_names, file_names in os.walk(module_root, followlinks=True):
        canonical_current = Path(current).resolve(strict=True)
        require_contained(canonical_current, module_root, label="module artifact directory")
        if canonical_current in visited_directories:
            raise ModuleSpecError(
                f"module artifact directory is reachable more than once: {current}"
            )
        visited_directories.add(canonical_current)
        directory_names[:] = sorted(
            name for name in directory_names if name not in IGNORED_DIRECTORY_NAMES
        )
        current_path = Path(current)
        for name in directory_names:
            require_contained(
                current_path / name,
                module_root,
                label="module artifact directory",
            )
        for name in sorted(file_names):
            path = current_path / name
            if path.suffix in IGNORED_FILE_SUFFIXES:
                continue
            require_contained(path, module_root, label="module artifact")
            relative = path.relative_to(module_root).as_posix().encode()
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            try:
                payload = path.read_bytes()
            except OSError as exc:
                raise ModuleSpecError(f"cannot read module artifact {path}: {exc}") from exc
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
    return digest.hexdigest()
