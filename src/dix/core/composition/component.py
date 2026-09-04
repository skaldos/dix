from __future__ import annotations

import importlib.util
import inspect
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from dix.core.registry import ComponentRegistry

from .models import (
    CompositionDefinition,
    CompositionDescriptor,
    CompositionDependencyEdge,
    CompositionDependencyGraph,
    CompositionFunctionDescriptor,
    CompositionInstance,
    CompositionInstanceSpec,
    CompositionRuntimeContext,
    LoadedCompositionDefinition,
    LoadedModule,
    ModuleDescriptor,
    ModuleInspection,
)
from .runtime import (
    CompositionApi,
    CompositionRuntimeError,
    create_api,
    describe_runtime_functions,
    validate_runtime_constructor,
)
from .spec import discover_modules, inspect_module, inspect_spec


class CompositionComponentError(Exception):
    """Raised when composition modules cannot be loaded or managed safely."""


class CompositionLifecycleError(CompositionComponentError):
    """Report a lifecycle failure together with any failed cleanup operations."""

    def __init__(self, message: str, errors: tuple[BaseException, ...]) -> None:
        self.errors = errors
        details = "; ".join(f"{type(item).__name__}: {item}" for item in errors)
        super().__init__(f"{message}: {details}")


class CompositionComponent:
    """Authoritative registry for trusted composition module definitions."""

    component_id = "composition"

    def __init__(self, components: ComponentRegistry) -> None:
        self._components = components
        self._import_namespace = uuid4().hex
        self._modules: dict[str, LoadedModule] = {}
        self._definitions: dict[str, LoadedCompositionDefinition] = {}
        self._instances: dict[tuple[str, str], CompositionInstance] = {}
        self._root_graphs: dict[tuple[str, str], tuple[str, ...]] = {}

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
        owned_graphs: list[tuple[str, str]] = []
        for graph_key, instance_ids in self._root_graphs.items():
            root = self._instances[(graph_key[0], graph_key[1])]
            graph_uses_target = any(
                self._instances[(graph_key[0], instance_id)].definition_id in owned_ids
                for instance_id in instance_ids
            )
            if not graph_uses_target:
                continue
            if root.module_id != module_id:
                raise CompositionComponentError(
                    f"module '{module_id}' is used by externally rooted instance graph "
                    f"'{root.scope_id}/{root.id}'"
                )
            owned_graphs.append(graph_key)
        for scope_id, root_instance_id in owned_graphs:
            self.destroy_instance(scope_id, root_instance_id)
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
            aliases = tuple((*sorted(definition.components), *sorted(definition.compositions)))
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
                api = create_api(definition, runtime, child_apis)
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
        if any(
            self._instances[(scope_id, graph_instance_id)].state == "active"
            for graph_instance_id in graph
        ):
            self.stop_instance(scope_id, instance_id)
        for graph_instance_id in reversed(graph):
            del self._instances[(scope_id, graph_instance_id)]
        del self._root_graphs[key]

    def start_instance(self, scope_id: str, instance_id: str) -> CompositionInstance:
        graph = self._require_root_graph(scope_id, instance_id)
        instances = [self._instances[(scope_id, item)] for item in graph]
        if any(item.state != "created" for item in instances):
            raise CompositionComponentError(
                f"composition instance graph cannot be started from its current state: "
                f"{scope_id}/{instance_id}"
            )
        started: list[CompositionInstance] = []
        try:
            for instance in instances:
                self._call_lifecycle(instance, "start")
                instance.state = "active"
                started.append(instance)
        except Exception as start_error:
            cleanup_errors: list[BaseException] = []
            for started_instance in reversed(started):
                try:
                    self._call_lifecycle(started_instance, "stop")
                    started_instance.state = "stopped"
                except Exception as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            for graph_instance_id in reversed(graph):
                del self._instances[(scope_id, graph_instance_id)]
            del self._root_graphs[(scope_id, instance_id)]
            raise CompositionLifecycleError(
                f"composition start failed for {scope_id}/{instance_id}",
                (start_error, *cleanup_errors),
            ) from start_error
        return self.require_instance(scope_id, instance_id)

    def stop_instance(self, scope_id: str, instance_id: str) -> CompositionInstance:
        graph = self._require_root_graph(scope_id, instance_id)
        instances = [self._instances[(scope_id, item)] for item in graph]
        if any(item.state == "created" for item in instances):
            raise CompositionComponentError(
                f"composition instance graph has not been started: {scope_id}/{instance_id}"
            )
        if all(item.state == "stopped" for item in instances):
            raise CompositionComponentError(
                f"composition instance graph is already stopped: {scope_id}/{instance_id}"
            )
        errors: list[BaseException] = []
        for instance in reversed(instances):
            if instance.state != "active":
                continue
            try:
                self._call_lifecycle(instance, "stop")
                instance.state = "stopped"
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise CompositionLifecycleError(
                f"composition stop failed for {scope_id}/{instance_id}",
                tuple(errors),
            )
        return self.require_instance(scope_id, instance_id)

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
                    f"lifecycle operations require a root instance: {scope_id}/{instance_id}"
                ) from exc
            raise CompositionComponentError(
                f"composition root instance not found: {scope_id}/{instance_id}"
            ) from exc

    @staticmethod
    def _call_lifecycle(instance: CompositionInstance, method_name: str) -> None:
        method = getattr(instance.runtime, method_name, None)
        if method is None:
            return
        if not callable(method):
            raise CompositionComponentError(
                f"lifecycle attribute is not callable: "
                f"{instance.definition_id}.{method_name}"
            )
        result = method()
        if inspect.isawaitable(result):
            raise CompositionComponentError(
                f"async lifecycle hooks are not supported: "
                f"{instance.definition_id}.{method_name}"
            )

    def describe_composition(self, composition_id: str) -> CompositionDescriptor:
        loaded_definition = self._require_loaded_definition(composition_id)
        module = self.require_module(loaded_definition.definition.module_id)
        return CompositionDescriptor(
            definition=loaded_definition.definition,
            functions=describe_runtime_functions(
                loaded_definition.definition,
                loaded_definition.runtime_type,
            ),
            module=ModuleDescriptor(
                id=module.inspection.id,
                root=module.inspection.root,
                artifact_digest=module.inspection.artifact_digest,
                loaded=True,
                composition_ids=tuple(sorted(module.compositions)),
            ),
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
        descriptors: dict[str, set[str]] = {}
        for definition_id in graph.nodes:
            loaded = self._require_loaded_definition(definition_id)
            definition = loaded.definition
            aliases = tuple((*sorted(definition.components), *sorted(definition.compositions)))
            validate_runtime_constructor(loaded.runtime_type, aliases)
            descriptors[definition_id] = {
                item.id for item in describe_runtime_functions(definition, loaded.runtime_type)
            }
        for definition_id in graph.nodes:
            definition = self.require_definition(definition_id)
            for descriptor in describe_runtime_functions(
                definition,
                self._require_loaded_definition(definition_id).runtime_type,
            ):
                if descriptor.origin is None:
                    continue
                alias, function_id = descriptor.origin.split(".", 1)
                target = definition.compositions[alias].use
                if function_id not in descriptors[target]:
                    raise CompositionRuntimeError(
                        f"wrapper origin '{descriptor.origin}' in '{definition_id}' refers to "
                        f"undeclared function '{target}.{function_id}'"
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
    CompositionDescriptor,
    CompositionFunctionDescriptor,
    CompositionInstance,
    CompositionInstanceSpec,
    CompositionRuntimeContext,
