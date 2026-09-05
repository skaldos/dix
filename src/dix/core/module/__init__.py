"""Shared module inspection models and structural discovery."""

from .errors import ModuleSpecError
from .inspection import discover_modules, inspect_module
from .models import ModuleDescriptor, ModuleInspection
from .validation import normalize_module_id

__all__ = [
    "ModuleDescriptor",
    "ModuleInspection",
    "ModuleSpecError",
    "discover_modules",
    "inspect_module",
    "normalize_module_id",
]
