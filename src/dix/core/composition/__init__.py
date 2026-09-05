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
    CompositionSource,
    LoadedCompositionDefinition,
)
from .runtime import CompositionApi, CompositionRuntimeError
from .component import CompositionComponent, CompositionComponentError
from dix.core.module import (
    ModuleDescriptor,
    ModuleInspection,
    discover_modules,
    inspect_module,
    normalize_module_id,
)
from .spec import (
    CompositionSpecError,
    inspect_composition_source,
    inspect_spec,
    normalize_effective_composition_id,
    normalize_local_id,
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
    "CompositionSource",
    "CompositionSpecError",
    "LoadedCompositionDefinition",
    "ModuleDescriptor",
    "ModuleInspection",
    "discover_modules",
    "inspect_module",
    "inspect_composition_source",
    "inspect_spec",
    "normalize_effective_composition_id",
    "normalize_local_id",
    "normalize_module_id",
]
