"""Inspectable composition definitions and structural module discovery."""

from .models import (
    CompositionDefinition,
    CompositionDependencyEdge,
    CompositionDependencyGraph,
    CompositionDependencySpec,
    CompositionFunctionSpec,
    LoadedCompositionDefinition,
    LoadedModule,
    ModuleDescriptor,
    ModuleInspection,
)
from .component import CompositionComponent, CompositionComponentError
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
    "CompositionComponent",
    "CompositionComponentError",
    "CompositionDefinition",
    "CompositionDependencyEdge",
    "CompositionDependencyGraph",
    "CompositionDependencySpec",
    "CompositionFunctionSpec",
    "CompositionSpecError",
    "LoadedCompositionDefinition",
    "LoadedModule",
    "ModuleDescriptor",
    "ModuleInspection",
    "discover_modules",
    "inspect_module",
    "inspect_spec",
    "normalize_effective_composition_id",
    "normalize_local_id",
    "normalize_module_id",
]
