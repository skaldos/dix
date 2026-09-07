"""Inspectable composition definitions and structural module discovery."""

from dix.core.module import (
    ModuleDescriptor,
    ModuleInspection,
    discover_modules,
    inspect_module,
    normalize_module_id,
)

from .component import CompositionComponent, CompositionComponentError
from .models import (
    CompositionDefinition,
    CompositionDependencyEdge,
    CompositionDependencyGraph,
    CompositionDependencySpec,
    CompositionDescriptor,
    CompositionFunctionDescriptor,
    CompositionFunctionSpec,
    CompositionInstance,
    CompositionInstanceSpec,
    CompositionRuntimeContext,
    CompositionSource,
    LoadedCompositionDefinition,
)
from .runtime import CompositionApi, CompositionRuntimeError
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
    "CompositionDependencyEdge",
    "CompositionDependencyGraph",
    "CompositionDependencySpec",
    "CompositionDescriptor",
    "CompositionFunctionDescriptor",
    "CompositionFunctionSpec",
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
    "inspect_composition_source",
    "inspect_module",
    "inspect_spec",
    "normalize_effective_composition_id",
    "normalize_local_id",
    "normalize_module_id",
]
