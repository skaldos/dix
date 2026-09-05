"""Shared module inspection models and structural discovery."""

from .errors import ModuleSpecError
from .models import LoadedModule, ModuleDescriptor, ModuleInspection
from .validation import normalize_module_id


def inspect_module(*args, **kwargs):
    from .inspection import inspect_module as implementation

    return implementation(*args, **kwargs)


def discover_modules(*args, **kwargs):
    from .inspection import discover_modules as implementation

    return implementation(*args, **kwargs)


__all__ = [
    "LoadedModule",
    "ModuleDescriptor",
    "ModuleInspection",
    "ModuleSpecError",
    "discover_modules",
    "inspect_module",
    "normalize_module_id",
]
