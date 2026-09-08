from __future__ import annotations

import importlib.util
import inspect
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from dix.core.contract import ContractDefinition, ContractReference
from dix.core.model import ModelArtifactDefinition, ModelReference
from dix.core.norn import NornComponent
from dix.core.registry import ComponentRegistry

from .models import (
    CompositionDefinition,
    CompositionDependencyEdge,
    CompositionDependencyGraph,
    CompositionDescriptor,
    CompositionFunctionDescriptor,
    CompositionInstance,
    CompositionInstanceSpec,
    CompositionRuntimeContext,
    LoadedCompositionDefinition,
)
from .runtime import (
    CompositionApi,
    CompositionRuntimeError,
    create_api,
    describe_runtime_functions,
    validate_runtime_constructor,
)
from .spec import inspect_spec

if TYPE_CHECKING:
    from dix.core.module.models import ModuleDescriptor


class CompositionComponentError(Exception):
    """Raised when composition modules cannot be loaded or managed safely."""


class CompositionComponent:
    """Authoritative registry for trusted composition module definitions."""

    component_id = "composition"

    def __init__(self, components: ComponentRegistry) -> None:
        self._components = components
        self._import_namespace = uuid4().hex
        self._definitions: dict[str, LoadedCompositionDefinition] = {}
        self._instances: dict[tuple[str, str], CompositionInstance] = {}
        self._root_graphs: dict[tuple[str, str], tuple[str, ...]] = {}

    def inspect_spec(self, path: Path, *, module_id: str) -> CompositionDefinition:
        return inspect_spec(path, module_id=module_id)

    def _stage_definitions(
        self,
        definitions: Sequence[CompositionDefinition],
        *,
        artifact_digest: str,
        module: ModuleDescriptor,
        contracts: Mapping[ContractReference, ContractDefinition],
        models: Mapping[ModelReference, ModelArtifactDefinition],
    ) -> dict[str, LoadedCompositionDefinition]:
        imported: list[str] = []
        staged: dict[str, LoadedCompositionDefinition] = {}
        try:
            runtimes: list[tuple[CompositionDefinition, type[object], str]] = []
            for definition in definitions:
                runtime_type, module_name = self._import_runtime(definition, artifact_digest)
                imported.append(module_name)
                runtimes.append((definition, runtime_type, module_name))
            for definition, runtime_type, module_name in runtimes:
                aliases = (*sorted(definition.components), *sorted(definition.compositions))
                validate_runtime_constructor(runtime_type, aliases)
                functions = describe_runtime_functions(
                    definition,
                    runtime_type,
                    contracts,
                    models,
                )
                staged[definition.id] = LoadedCompositionDefinition(
                    definition=definition,
                    runtime_type=runtime_type,
                    runtime_module_name=module_name,
                    module=module,
                    functions=functions,
                )
        except Exception:
            for module_name in imported:
                self._remove_runtime_modules(module_name)
            raise
        return staged

    def _validate_staged_definitions(
        self,
        staged: Mapping[str, LoadedCompositionDefinition],
    ) -> None:
        candidates = {**self._definitions, **staged}
        for composition_id in sorted(staged):
            self._validate_loaded_graph(composition_id, candidates)

    @staticmethod
    def _describe_candidate_functions(
        loaded: LoadedCompositionDefinition,
    ) -> tuple[CompositionFunctionDescriptor, ...]:
        return loaded.functions

    def _publish_definitions(self, staged: Mapping[str, LoadedCompositionDefinition]) -> None:
        self._definitions.update(staged)

    def _unpublish_definitions(self, definition_ids: Sequence[str]) -> None:
        for definition_id in definition_ids:
            self._definitions.pop(definition_id, None)

    def _discard_staged_definitions(
        self, staged: Mapping[str, LoadedCompositionDefinition]
    ) -> None:
        for loaded in staged.values():
            self._remove_runtime_modules(loaded.runtime_module_name)

    def _unload_blockers(self, module_id: str, owned_ids: set[str]) -> tuple[str, ...]:
        blockers: list[str] = []
        for definition_id, candidate in sorted(self._definitions.items()):
            if definition_id in owned_ids:
                continue
            for dependency in candidate.definition.compositions.values():
                if dependency.use in owned_ids:
                    blockers.append(
                        "loaded composition definition "
                        f"'{definition_id}' requires '{dependency.use}' from module '{module_id}'"
                    )
        for graph_key, instance_ids in sorted(self._root_graphs.items()):
            root = self._instances[(graph_key[0], graph_key[1])]
            for instance_id in sorted(instance_ids):
                instance = self._instances[(graph_key[0], instance_id)]
                if instance.definition_id not in owned_ids:
                    continue
                blockers.append(
                    f"live composition definition '{instance.definition_id}' from module "
                    f"'{module_id}': scope='{root.scope_id}', instance='{instance.id}', "
                    f"root='{root.id}'"
                )
        return tuple(sorted(set(blockers)))

    def definitions(self) -> tuple[CompositionDefinition, ...]:
        return tuple(self._definitions[item].definition for item in sorted(self._definitions))

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

    def create_instance(
        self,
        spec: CompositionInstanceSpec,
        *,
        owner_scope_id: str,
    ) -> CompositionInstance:
        owner_scope = owner_scope_id.strip()
        if not owner_scope:
            raise CompositionComponentError("owner scope id must not be empty")
        root_key = (owner_scope, spec.id)
        if root_key in self._root_graphs or root_key in self._instances:
            raise CompositionComponentError(
                f"composition root instance already exists: {owner_scope}/{spec.id}"
            )
        try:
            self._validate_runtime_graph(spec.use)
        except Exception as exc:
            raise CompositionComponentError(
                f"cannot create composition instance '{owner_scope}/{spec.id}': {exc}"
            ) from exc
        staged: dict[str, CompositionInstance] = {}

        def build(
            definition_id: str,
            instance_id: str,
            config: Mapping[str, Any],
            config_base_dir: Path,
            parent_instance_id: str | None,
        ) -> CompositionInstance:
            loaded_definition = self._require_loaded_definition(definition_id)
            definition = loaded_definition.definition
            component_scope = self._components.create_scope(
                f"composition:{owner_scope}:{instance_id}"
            )
            child_apis: dict[str, CompositionApi] = {}
            injected: dict[str, object] = {}
            for alias, component_id in sorted(definition.components.items()):
                injected[alias] = component_scope.require(component_id, object)
            for alias, dependency in sorted(definition.compositions.items()):
                child_id = f"{instance_id}/{alias}"
                child = build(
                    dependency.use,
                    child_id,
                    dict(dependency.config),
                    definition.composition_root,
                    instance_id,
                )
                child_apis[alias] = child.api
                injected[alias] = child.api
            aliases = (*sorted(definition.components), *sorted(definition.compositions))
            validate_runtime_constructor(loaded_definition.runtime_type, aliases)
            context = CompositionRuntimeContext(
                instance_id=instance_id,
                composition_id=definition.id,
                module_id=definition.module_id,
                module_root=definition.module_root,
                composition_root=definition.composition_root,
                config_base_dir=config_base_dir.expanduser().resolve(),
                owner_scope_id=owner_scope,
            )
            try:
                runtime = loaded_definition.runtime_type(
                    context=context,
                    config=config,
                    **injected,
                )
                api = create_api(
                    definition,
                    runtime,
                    child_apis,
                    loaded_definition.functions,
                    component_scope.require("norn", NornComponent),
                )
            except CompositionRuntimeError:
                raise
            except Exception as exc:
                raise CompositionRuntimeError(
                    f"cannot create composition runtime '{definition.id}': {exc}"
                ) from exc
            instance = CompositionInstance(
                id=instance_id,
                definition_id=definition.id,
                module_id=definition.module_id,
                scope_id=owner_scope,
                root_instance_id=spec.id,
                parent_instance_id=parent_instance_id,
                runtime=runtime,
                api=api,
                context=context,
            )
            staged[instance_id] = instance
            return instance

        try:
            root = build(
                spec.use,
                spec.id,
                dict(spec.config),
                spec.config_base_dir,
                None,
            )
        except Exception as exc:
            raise CompositionComponentError(
                f"cannot create composition instance '{owner_scope}/{spec.id}': {exc}"
            ) from exc
        for instance_id, instance in staged.items():
            self._instances[(owner_scope, instance_id)] = instance
        self._root_graphs[root_key] = tuple(staged)
        return root

    def destroy_instance(self, scope_id: str, instance_id: str) -> None:
        key = (scope_id, instance_id)
        try:
            graph = self._root_graphs[key]
        except KeyError as exc:
            if key in self._instances:
                raise CompositionComponentError(
                    f"only root composition instances can be destroyed: {scope_id}/{instance_id}"
                ) from exc
            raise CompositionComponentError(
                f"composition root instance not found: {scope_id}/{instance_id}"
            ) from exc
        for graph_instance_id in reversed(graph):
            del self._instances[(scope_id, graph_instance_id)]
        del self._root_graphs[key]

    def _discard_instance_graph(self, scope_id: str, instance_id: str) -> None:
        """Remove one graph during parent construction rollback."""
        graph = self._require_root_graph(scope_id, instance_id)
        for graph_instance_id in reversed(graph):
            del self._instances[(scope_id, graph_instance_id)]
        del self._root_graphs[(scope_id, instance_id)]

    def instances(self, *, scope_id: str | None = None) -> tuple[CompositionInstance, ...]:
        values = (
            instance
            for (candidate_scope, _), instance in self._instances.items()
            if scope_id is None or candidate_scope == scope_id
        )
        return tuple(sorted(values, key=lambda item: (item.scope_id, item.id)))

    def require_instance(self, scope_id: str, instance_id: str) -> CompositionInstance:
        try:
            return self._instances[(scope_id, instance_id)]
        except KeyError as exc:
            raise CompositionComponentError(
                f"composition instance not found: {scope_id}/{instance_id}"
            ) from exc

    def _require_root_graph(self, scope_id: str, instance_id: str) -> tuple[str, ...]:
        try:
            return self._root_graphs[(scope_id, instance_id)]
        except KeyError as exc:
            if (scope_id, instance_id) in self._instances:
                raise CompositionComponentError(
                    f"operations require a root composition instance: {scope_id}/{instance_id}"
                ) from exc
            raise CompositionComponentError(
                f"composition root instance not found: {scope_id}/{instance_id}"
            ) from exc

    def describe_composition(self, composition_id: str) -> CompositionDescriptor:
        loaded_definition = self._require_loaded_definition(composition_id)
        descriptors = self._describe_function_graph(composition_id)
        return CompositionDescriptor(
            definition=loaded_definition.definition,
            functions=descriptors[composition_id],
            module=loaded_definition.module,
        )

    def describe_function(
        self,
        composition_id: str,
        function_id: str,
    ) -> CompositionFunctionDescriptor:
        for descriptor in self.describe_composition(composition_id).functions:
            if descriptor.id == function_id:
                return descriptor
        raise CompositionComponentError(
            f"composition function is not declared: {composition_id}.{function_id}"
        )

    def _validate_runtime_graph(self, composition_id: str) -> None:
        graph = self.describe_dependency_graph(composition_id)
        for definition_id in graph.nodes:
            loaded = self._require_loaded_definition(definition_id)
            definition = loaded.definition
            aliases = (*sorted(definition.components), *sorted(definition.compositions))
            validate_runtime_constructor(loaded.runtime_type, aliases)
        self._describe_function_graph(composition_id)

    def _validate_loaded_graph(
        self,
        composition_id: str,
        candidates: Mapping[str, LoadedCompositionDefinition],
    ) -> None:
        visiting: list[str] = []
        visited: set[str] = set()

        def visit(definition_id: str) -> None:
            if definition_id in visiting:
                start = visiting.index(definition_id)
                cycle = (*visiting[start:], definition_id)
                raise CompositionComponentError(
                    f"composition dependency cycle: {' -> '.join(cycle)}"
                )
            if definition_id in visited:
                return
            try:
                loaded = candidates[definition_id]
            except KeyError as exc:
                raise CompositionComponentError(
                    f"composition definition is not loaded: {definition_id}"
                ) from exc
            visiting.append(definition_id)
            definition = loaded.definition
            for component_id in definition.components.values():
                self._components.require_provider(component_id)
            for dependency in definition.compositions.values():
                visit(dependency.use)
            aliases = (*sorted(definition.components), *sorted(definition.compositions))
            validate_runtime_constructor(loaded.runtime_type, aliases)
            visiting.pop()
            visited.add(definition_id)

        visit(composition_id)
        descriptors = {
            definition_id: candidates[definition_id].functions
            for definition_id in visited
        }
        function_ids = {
            definition_id: {item.id for item in values}
            for definition_id, values in descriptors.items()
        }
        for definition_id, values in descriptors.items():
            definition = candidates[definition_id].definition
            for descriptor in values:
                if descriptor.origin is None:
                    continue
                alias, function_id = descriptor.origin.split(".", 1)
                target = definition.compositions[alias].use
                if function_id not in function_ids[target]:
                    raise CompositionRuntimeError(
                        f"wrapper origin '{descriptor.origin}' in '{definition_id}' refers to "
                        f"undeclared function '{target}.{function_id}'"
                    )

    def _describe_function_graph(
        self,
        composition_id: str,
    ) -> dict[str, tuple[CompositionFunctionDescriptor, ...]]:
        graph = self.describe_dependency_graph(composition_id)
        descriptors = {
            definition_id: self._require_loaded_definition(definition_id).functions
            for definition_id in graph.nodes
        }
        function_ids = {
            definition_id: {item.id for item in values}
            for definition_id, values in descriptors.items()
        }
        for definition_id, values in descriptors.items():
            definition = self.require_definition(definition_id)
            for descriptor in values:
                if descriptor.origin is None:
                    continue
                alias, function_id = descriptor.origin.split(".", 1)
                target = definition.compositions[alias].use
                if function_id not in function_ids[target]:
                    raise CompositionRuntimeError(
                        f"wrapper origin '{descriptor.origin}' in '{definition_id}' refers to "
                        f"undeclared function '{target}.{function_id}'"
                    )
        return descriptors

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
        module_name = f"_dix_composition_{self._import_namespace}_{safe_id}_{artifact_digest[:16]}"
        if module_name in sys.modules:
            raise CompositionComponentError(
                f"composition runtime module name is already active: {definition.id}"
            )
        module_spec = importlib.util.spec_from_file_location(
            module_name,
            definition.runtime_path,
            submodule_search_locations=[str(definition.composition_root)],
        )
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
            CompositionComponent._remove_runtime_modules(module_name)
            raise
        return runtime_type, module_name

    @staticmethod
    def _remove_runtime_modules(module_name: str) -> None:
        for active_name in tuple(sys.modules):
            if active_name == module_name or active_name.startswith(f"{module_name}."):
                sys.modules.pop(active_name, None)
