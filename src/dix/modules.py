from __future__ import annotations

from pathlib import Path

from dix.core.module import ModuleSpecError, normalize_module_id


class FirstPartyModuleError(LookupError):
    """Raised when one explicitly requested first-party module is unavailable."""


def first_party_module_path(module_id: str) -> Path:
    """Resolve one bundled DIX module without discovery or implicit loading."""
    try:
        normalized_id = normalize_module_id(module_id)
    except ModuleSpecError as exc:
        raise FirstPartyModuleError(f"invalid first-party module id: {exc}") from exc

    relative = Path(*normalized_id.split("/"))
    package_root = Path(__file__).resolve().parent
    candidates = (
        package_root / "_modules" / relative,
        package_root.parents[1] / "modules" / relative,
    )
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_dir():
            return resolved
    raise FirstPartyModuleError(f"first-party module is not available: {normalized_id}")


__all__ = ["FirstPartyModuleError", "first_party_module_path"]
