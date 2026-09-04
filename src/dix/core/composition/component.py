from __future__ import annotations

import importlib.util
import inspect
import sys
from collections.abc import Iterable
from pathlib import Path
from uuid import uuid4

from dix.core.registry import ComponentRegistry

from .models import (
    CompositionDefinition,
    CompositionDependencyEdge,
    CompositionDependencyGraph,
    LoadedCompositionDefinition,
    LoadedModule,
    ModuleDescriptor,
    ModuleInspection,
)
from .spec import discover_modules, inspect_module, inspect_spec


class CompositionComponentError(Exception):
    """Raised when composition modules cannot be loaded or managed safely."""


class CompositionComponent:
    """Authoritative registry for trusted composition module definitions."""

    component_id = "composition"

    def __init__(self, components: ComponentRegistry) -> None:
        self._components = components
        self._import_namespace = uuid4().hex
        self._modules: dict[str, LoadedModule] = {}
        self._definitions: dict[str, LoadedCompositionDefinition] = {}

    def inspect_spec(self, path: Path, *, module_id: str) -> CompositionDefinition:
        return inspect_spec(path, module_id=module_id)

    def inspect_module(self, root: Path, *, module_id: str) -> ModuleInspection:
        return inspect_module(root, module_id=module_id)

    def discover_modules(self, roots: Iterable[Path]) -> tuple[ModuleInspection, ...]:
        return discover_modules(roots)

    def load_module(
        self,
        root: Path,
        *,
        module_id: str,
        expected_artifact_digest: str | None = None,
    ) -> LoadedModule:
        """Import and publish one complete module bundle or publish nothing."""
        inspection = inspect_module(root, module_id=module_id)
        if (
            expected_artifact_digest is not None
            and inspection.artifact_digest != expected_artifact_digest
        ):
            raise CompositionComponentError(
                f"module artifact digest mismatch for '{inspection.id}': "
                f"expected {expected_artifact_digest}, got {inspection.artifact_digest}"
            )
        if inspection.id in self._modules:
            raise CompositionComponentError(f"module already loaded: {inspection.id}")
        duplicates = sorted(
            definition.id
            for definition in inspection.definitions
            if definition.id in self._definitions
        )
        if duplicates:
            raise CompositionComponentError(
                f"composition definition already loaded: {duplicates[0]}"
            )

        imported: list[str] = []
        staged: dict[str, LoadedCompositionDefinition] = {}
        try:
            for definition in inspection.definitions:
                runtime_type, module_name = self._import_runtime(
                    definition,
                    inspection.artifact_digest,
                )
                imported.append(module_name)
                staged[definition.id] = LoadedCompositionDefinition(
                    definition=definition,
                    runtime_type=runtime_type,
                    runtime_module_name=module_name,
                )
        except Exception:
            for module_name in imported:
                sys.modules.pop(module_name, None)
            raise

        loaded = LoadedModule(
            inspection=inspection,
            compositions={item: staged[item] for item in sorted(staged)},
        )
        self._modules[inspection.id] = loaded
        self._definitions.update(staged)
        return loaded

    def unload_module(self, module_id: str) -> LoadedModule:
        loaded = self.require_module(module_id)
        owned_ids = set(loaded.compositions)
        for definition_id, candidate in self._definitions.items():
            if definition_id in owned_ids:
                continue
            for dependency in candidate.definition.compositions.values():
                if dependency.use in owned_ids:
                    raise CompositionComponentError(
                        f"module '{module_id}' is required by loaded composition "
                        f"'{definition_id}'"
                    )
        del self._modules[module_id]
        for definition_id, definition in loaded.compositions.items():
            del self._definitions[definition_id]
            sys.modules.pop(definition.runtime_module_name, None)
        return loaded

    def modules(self) -> tuple[LoadedModule, ...]:
        return tuple(self._modules[item] for item in sorted(self._modules))

    def module_descriptors(self) -> tuple[ModuleDescriptor, ...]:
        return tuple(
            ModuleDescriptor(
                id=loaded.inspection.id,
                root=loaded.inspection.root,
                artifact_digest=loaded.inspection.artifact_digest,
                loaded=True,
                composition_ids=tuple(sorted(loaded.compositions)),
            )
            for loaded in self.modules()
        )

    def require_module(self, module_id: str) -> LoadedModule:
        try:
            return self._modules[module_id]
        except KeyError as exc:
            raise CompositionComponentError(f"module is not loaded: {module_id}") from exc

    def definitions(self) -> tuple[CompositionDefinition, ...]:
        return tuple(
            self._definitions[item].definition for item in sorted(self._definitions)
        )

    def require_definition(self, composition_id: str) -> CompositionDefinition:
        return self._require_loaded_definition(composition_id).definition

    def describe_dependency_graph(
        self,
        composition_id: str,
    ) -> CompositionDependencyGraph:
        self.require_definition(composition_id)
        nodes: set[str] = set()
        edges: list[CompositionDependencyEdge] = []
        visiting: list[str] = []

        def visit(definition_id: str) -> None:
            if definition_id in visiting:
                start = visiting.index(definition_id)
                cycle = (*visiting[start:], definition_id)
                raise CompositionComponentError(
                    f"composition dependency cycle: {' -> '.join(cycle)}"
                )
            if definition_id in nodes:
                return
            definition = self.require_definition(definition_id)
            visiting.append(definition_id)
            for alias, target in sorted(definition.components.items()):
                self._components.require_provider(target)
                edges.append(
                    CompositionDependencyEdge(
                        source=definition_id,
                        alias=alias,
                        target=target,
                        kind="component",
                    )
                )
            for alias, dependency in sorted(definition.compositions.items()):
                edges.append(
                    CompositionDependencyEdge(
                        source=definition_id,
                        alias=alias,
                        target=dependency.use,
                        kind="composition",
                    )
                )
                visit(dependency.use)
            visiting.pop()
            nodes.add(definition_id)

        visit(composition_id)
        return CompositionDependencyGraph(
            root=composition_id,
            nodes=tuple(sorted(nodes)),
            edges=tuple(
                sorted(edges, key=lambda item: (item.source, item.kind, item.alias, item.target))
            ),
        )

    def _require_loaded_definition(self, composition_id: str) -> LoadedCompositionDefinition:
        try:
            return self._definitions[composition_id]
        except KeyError as exc:
            raise CompositionComponentError(
                f"composition definition is not loaded: {composition_id}"
            ) from exc

    def _import_runtime(
        self,
        definition: CompositionDefinition,
        artifact_digest: str,
    ) -> tuple[type[object], str]:
        safe_id = definition.id.replace("/", "_").replace("-", "_")
        module_name = (
            f"_dix_composition_{self._import_namespace}_{safe_id}_{artifact_digest[:16]}"
        )
        if module_name in sys.modules:
            raise CompositionComponentError(
                f"composition runtime module name is already active: {definition.id}"
            )
        module_spec = importlib.util.spec_from_file_location(module_name, definition.runtime_path)
        if module_spec is None or module_spec.loader is None:
            raise CompositionComponentError(
                f"cannot create runtime import spec for composition: {definition.id}"
            )
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        try:
            module_spec.loader.exec_module(module)
            runtime_type = getattr(module, "Runtime", None)
            if not inspect.isclass(runtime_type) or runtime_type.__module__ != module_name:
                raise CompositionComponentError(
                    f"composition '{definition.id}' must define runtime.py:Runtime"
                )
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        return runtime_type, module_name
