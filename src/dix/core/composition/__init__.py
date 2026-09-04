"""Inspectable composition definitions and structural module discovery."""

from .models import (
    CompositionDefinition,
    CompositionDescriptor,
    CompositionDependencyEdge,
    CompositionDependencyGraph,
    CompositionDependencySpec,
    CompositionFunctionDescriptor,
    CompositionFunctionSpec,
    CompositionInstance,
    CompositionInstanceSpec,
    CompositionRuntimeContext,
    LoadedCompositionDefinition,
    LoadedModule,
    ModuleDescriptor,
    ModuleInspection,
)
from .runtime import CompositionApi, CompositionRuntimeError
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
    "CompositionApi",
    "CompositionComponent",
    "CompositionComponentError",
    "CompositionDefinition",
    "CompositionDescriptor",
    "CompositionDependencyEdge",
    "CompositionDependencyGraph",
    "CompositionDependencySpec",
    "CompositionFunctionSpec",
    "CompositionFunctionDescriptor",
    "CompositionInstance",
    "CompositionInstanceSpec",
    "CompositionRuntimeContext",
    "CompositionRuntimeError",
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
