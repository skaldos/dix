"""Inspectable composition definitions and structural module discovery."""

from .models import (
    CompositionDefinition,
    CompositionDependencySpec,
    CompositionFunctionSpec,
    ModuleInspection,
)
from .spec import (
    CompositionSpecError,
    discover_modules,
    inspect_module,
    inspect_spec,
    normalize_effective_composition_id,
    normalize_local_id,
    normalize_module_id,
)

__all__ = [
    "CompositionDefinition",
    "CompositionDependencySpec",
    "CompositionFunctionSpec",
    "CompositionSpecError",
    "ModuleInspection",
    "discover_modules",
    "inspect_module",
    "inspect_spec",
    "normalize_effective_composition_id",
    "normalize_local_id",
    "normalize_module_id",
]
