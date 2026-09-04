from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from dix.core.composition import (
    CompositionDefinition,
    CompositionFunctionDescriptor,
    CompositionSpecError,
    inspect_spec,
    normalize_effective_composition_id,
)
from dix.core.composition.runtime import describe_runtime_functions, validate_runtime_constructor
from dix.core.registry import ComponentRegistryError, create_core_component_registry

from .errors import CompositionGeneratorError


class CompositionFunctionResolver(Protocol):
    """Resolve live composition functions for runtime source generation."""

    def describe_function(
        self,
        composition_id: str,
        function_id: str,
    ) -> CompositionFunctionDescriptor: ...


class TrustedBuildFunctionResolver:
    """Inspect dependency runtimes without loading an incomplete target module.

    Runtime module loading remains atomic. This resolver is deliberately scoped to
    authoring: it resolves explicit composition IDs below trusted roots and imports
    only their transitive dependency runtimes into an isolated temporary namespace.
    """

    def __init__(self, trusted_module_roots: Iterable[Path]) -> None:
        self._trusted_roots = tuple(
            dict.fromkeys(
                self._resolve_trusted_root(path) for path in trusted_module_roots
            )
        )
        self._namespace = uuid4().hex
        self._components = create_core_component_registry()
        self._definitions: dict[str, CompositionDefinition] = {}
        self._descriptors: dict[str, tuple[CompositionFunctionDescriptor, ...]] = {}
        self._runtime_types: dict[str, type[object]] = {}
        self._runtime_modules: list[str] = []
        self._visiting: list[str] = []

    def __enter__(self) -> TrustedBuildFunctionResolver:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Remove every runtime imported for this build-time resolution."""
        for module_name in reversed(self._runtime_modules):
            self._remove_runtime_modules(module_name)
        self._runtime_modules.clear()

    def describe_function(
        self,
        composition_id: str,
        function_id: str,
    ) -> CompositionFunctionDescriptor:
        normalized_id = normalize_effective_composition_id(composition_id)
        descriptors = self._describe_composition(normalized_id)
        for descriptor in descriptors:
            if descriptor.id == function_id:
                return descriptor
        raise CompositionGeneratorError(
            f"composition function is not declared: {normalized_id}.{function_id}"
        )

    def _describe_composition(
        self,
        composition_id: str,
    ) -> tuple[CompositionFunctionDescriptor, ...]:
        if composition_id in self._descriptors:
            return self._descriptors[composition_id]
        if composition_id in self._visiting:
            start = self._visiting.index(composition_id)
            cycle = (*self._visiting[start:], composition_id)
            raise CompositionGeneratorError(
                f"composition dependency cycle during generation: {' -> '.join(cycle)}"
            )

        self._visiting.append(composition_id)
        try:
            definition = self._resolve_definition(composition_id)
            for component_id in definition.components.values():
                try:
                    self._components.require_provider(component_id)
                except ComponentRegistryError as exc:
                    raise CompositionGeneratorError(
                        f"unknown component '{component_id}' in composition "
                        f"'{composition_id}'"
                    ) from exc
            dependency_functions = {
                alias: {
                    item.id: item
                    for item in self._describe_composition(dependency.use)
                }
                for alias, dependency in definition.compositions.items()
            }
            runtime_type = self._import_runtime(definition)
            aliases = tuple(
                (*sorted(definition.components), *sorted(definition.compositions))
            )
            validate_runtime_constructor(runtime_type, aliases)
            descriptors = describe_runtime_functions(definition, runtime_type)
            for descriptor in descriptors:
                if descriptor.origin is None:
                    continue
                alias, dependency_function = descriptor.origin.split(".", 1)
                if dependency_function not in dependency_functions[alias]:
                    target = definition.compositions[alias].use
                    raise CompositionGeneratorError(
                        f"wrapper origin '{descriptor.origin}' in '{composition_id}' refers to "
                        f"undeclared function '{target}.{dependency_function}'"
                    )
            self._descriptors[composition_id] = descriptors
            return descriptors
        finally:
            self._visiting.pop()

    def _resolve_definition(self, composition_id: str) -> CompositionDefinition:
        if composition_id in self._definitions:
            return self._definitions[composition_id]
        module_id, local_id = composition_id.rsplit("/", 1)
        module_parts = module_id.split("/")
        candidates: list[tuple[Path, Path]] = []
        for trusted_root in self._trusted_roots:
            unresolved_module = trusted_root.joinpath(*module_parts)
            if not unresolved_module.exists():
                continue
            module_root = unresolved_module.resolve(strict=True)
            try:
                module_root.relative_to(trusted_root)
            except ValueError as exc:
                raise CompositionGeneratorError(
                    f"composition module escapes trusted root '{trusted_root}': {module_root}"
                ) from exc
            spec_path = module_root / "compositions" / local_id / "composition.toml"
            if spec_path.exists():
                candidates.append((spec_path, module_root))
        if not candidates:
            raise CompositionGeneratorError(
                f"composition dependency is not present in trusted roots: {composition_id}"
            )
        if len(candidates) > 1:
            locations = ", ".join(str(item[0]) for item in sorted(candidates))
            raise CompositionGeneratorError(
                f"duplicate composition dependency across trusted roots: "
                f"{composition_id} ({locations})"
            )
        spec_path, expected_module_root = candidates[0]
        try:
            definition = inspect_spec(spec_path, module_id=module_id)
        except CompositionSpecError as exc:
            raise CompositionGeneratorError(
                f"cannot inspect composition dependency '{composition_id}': {exc}"
            ) from exc
        if definition.module_root != expected_module_root:
            raise CompositionGeneratorError(
                f"composition dependency escapes trusted module root: {composition_id}"
            )
        self._definitions[composition_id] = definition
        return definition

    def _import_runtime(self, definition: CompositionDefinition) -> type[object]:
        if definition.id in self._runtime_types:
            return self._runtime_types[definition.id]
        safe_id = definition.id.replace("/", "_").replace("-", "_")
        identity = hashlib.sha256(definition.id.encode()).hexdigest()[:16]
        module_name = f"_dix_build_{self._namespace}_{safe_id}_{identity}"
        module_spec = importlib.util.spec_from_file_location(
            module_name,
            definition.runtime_path,
            submodule_search_locations=[str(definition.composition_root)],
        )
        if module_spec is None or module_spec.loader is None:
            raise CompositionGeneratorError(
                f"cannot create build-time runtime import for: {definition.id}"
            )
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        try:
            module_spec.loader.exec_module(module)
            runtime_type = getattr(module, "Runtime", None)
            if not inspect.isclass(runtime_type) or runtime_type.__module__ != module_name:
                raise CompositionGeneratorError(
                    f"composition '{definition.id}' must define runtime.py:Runtime"
                )
        except CompositionGeneratorError:
            self._remove_runtime_modules(module_name)
            raise
        except Exception as exc:
            self._remove_runtime_modules(module_name)
            raise CompositionGeneratorError(
                f"cannot import composition dependency runtime '{definition.id}': {exc}"
            ) from exc
        self._runtime_modules.append(module_name)
        self._runtime_types[definition.id] = runtime_type
        return runtime_type

    @staticmethod
    def _resolve_trusted_root(path: Path) -> Path:
        try:
            resolved = path.expanduser().resolve(strict=True)
        except OSError as exc:
            raise CompositionGeneratorError(
                f"trusted module root does not exist: {path}"
            ) from exc
        if not resolved.is_dir():
            raise CompositionGeneratorError(
                f"trusted module root is not a directory: {resolved}"
            )
        return resolved

    @staticmethod
    def _remove_runtime_modules(module_name: str) -> None:
        for active_name in tuple(sys.modules):
            if active_name == module_name or active_name.startswith(f"{module_name}."):
                sys.modules.pop(active_name, None)
