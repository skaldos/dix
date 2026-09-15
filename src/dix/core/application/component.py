from __future__ import annotations

import importlib.util
import inspect
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import uuid4

from dix.core.composition import (
    CompositionApi,
    CompositionComponent,
    CompositionInstanceSpec,
)
from dix.core.composition.models import CompositionInstance, LoadedCompositionDefinition
from dix.core.module.models import ModuleDescriptor

from .models import (
    ApplicationDefinition,
    ApplicationDependencyEdge,
    ApplicationDependencyGraph,
    ApplicationDescriptor,
    ApplicationFunctionDescriptor,
    ApplicationInstance,
    ApplicationInstanceSpec,
    ApplicationRuntimeContext,
    LoadedApplicationDefinition,
)
from .runtime import (
    ApplicationApi,
    ApplicationRuntimeError,
    create_api,
    describe_runtime_functions,
    validate_runtime_constructor,
)
from .spec import inspect_spec


class ApplicationComponentError(Exception):
    """Raised when application definitions cannot be loaded or inspected safely."""


class ApplicationComponent:
    """Own loaded application definitions independently from module publication."""

    component_id = "application"

    def __init__(self, compositions: CompositionComponent) -> None:
        self._compositions = compositions
        self._import_namespace = uuid4().hex
        self._definitions: dict[str, LoadedApplicationDefinition] = {}
        self._instances: dict[tuple[str, str], ApplicationInstance] = {}
        self._root_graphs: dict[tuple[str, str], tuple[str, ...]] = {}

    def inspect_spec(self, path, *, module_id: str) -> ApplicationDefinition:
        return inspect_spec(path, module_id=module_id)

    def definitions(self) -> tuple[ApplicationDefinition, ...]:
        return tuple(self._definitions[item].definition for item in sorted(self._definitions))

    def require_definition(self, application_id: str) -> ApplicationDefinition:
        return self._require_loaded_definition(application_id).definition

    def describe_dependency_graph(self, application_id: str) -> ApplicationDependencyGraph:
        self.require_definition(application_id)
        nodes: set[str] = set()
        edges: list[ApplicationDependencyEdge] = []
        visiting: list[str] = []

        def visit(candidate_id: str) -> None:
            if candidate_id in visiting:
                start = visiting.index(candidate_id)
                cycle = (*visiting[start:], candidate_id)
                raise ApplicationComponentError(
                    f"application dependency cycle: {' -> '.join(cycle)}"
                )
            if candidate_id in nodes:
                return
            definition = self.require_definition(candidate_id)
            visiting.append(candidate_id)
            for alias, dependency in sorted(definition.compositions.items()):
                self._compositions.require_definition(dependency.use)
                edges.append(
                    ApplicationDependencyEdge(
                        source=candidate_id,
                        alias=alias,
                        target=dependency.use,
                        kind="composition",
                    )
                )
            for alias, dependency in sorted(definition.applications.items()):
                edges.append(
                    ApplicationDependencyEdge(
                        source=candidate_id,
                        alias=alias,
                        target=dependency.use,
                        kind="application",
                    )
                )
                visit(dependency.use)
            visiting.pop()
            nodes.add(candidate_id)

        visit(application_id)
        return ApplicationDependencyGraph(
            root=application_id,
            nodes=tuple(sorted(nodes)),
            edges=tuple(
                sorted(
                    edges,
                    key=lambda item: (item.source, item.kind, item.alias, item.target),
                )
            ),
        )

    def describe_application(self, application_id: str) -> ApplicationDescriptor:
        loaded = self._require_loaded_definition(application_id)
        descriptors = self._describe_function_graph(
            application_id,
            self._definitions,
            {},
        )
        return ApplicationDescriptor(
            definition=loaded.definition,
            functions=descriptors[application_id],
            module=loaded.module,
        )

    def describe_function(
        self, application_id: str, function_id: str
    ) -> ApplicationFunctionDescriptor:
        for descriptor in self.describe_application(application_id).functions:
            if descriptor.id == function_id:
                return descriptor
        raise ApplicationComponentError(
            f"application function is not declared: {application_id}.{function_id}"
        )

    def create_instance(
        self,
        spec: ApplicationInstanceSpec,
        *,
        owner_scope_id: str,
    ) -> ApplicationInstance:
        owner_scope = owner_scope_id.strip()
        if not owner_scope:
            raise ApplicationComponentError("owner scope id must not be empty")
        root_key = (owner_scope, spec.id)
        if root_key in self._root_graphs or root_key in self._instances:
            raise ApplicationComponentError(
                f"application root instance already exists: {owner_scope}/{spec.id}"
            )
        self._validate_loaded_graph(spec.use, self._definitions, {})
        staged: dict[str, ApplicationInstance] = {}
        created_compositions: list[tuple[str, str]] = []

        def build(
            definition_id: str,
            instance_id: str,
            config: Mapping[str, object],
            config_base_dir: Path,
            parent_instance_id: str | None,
        ) -> ApplicationInstance:
            loaded = self._require_loaded_definition(definition_id)
            definition = loaded.definition
            composition_apis: dict[str, CompositionApi] = {}
            composition_instances: dict[str, CompositionInstance] = {}
            composition_owner = f"application:{owner_scope}:{instance_id}"
            for alias, dependency in sorted(definition.compositions.items()):
                composition = self._compositions.create_instance(
                    CompositionInstanceSpec(
                        alias,
                        dependency.use,
                        dependency.config,
                        definition.application_root,
                    ),
                    owner_scope_id=composition_owner,
                )
                created_compositions.append((composition_owner, alias))
                composition_instances[alias] = composition
                composition_apis[alias] = composition.api

            child_apis: dict[str, ApplicationApi] = {}
            for alias, dependency in sorted(definition.applications.items()):
                child_id = f"{instance_id}/{alias}"
                child = build(
                    dependency.use,
                    child_id,
                    dependency.config,
                    definition.application_root,
                    instance_id,
                )
                child_apis[alias] = child.api

            aliases = (*sorted(definition.compositions), *sorted(definition.applications))
            validate_runtime_constructor(loaded.runtime_type, aliases)
            context = ApplicationRuntimeContext(
                instance_id=instance_id,
                application_id=definition.id,
                module_id=definition.module_id,
                module_root=definition.module_root,
                application_root=definition.application_root,
                config_base_dir=config_base_dir.expanduser().resolve(),
                owner_scope_id=owner_scope,
            )
            injected = {**composition_apis, **child_apis}
            try:
                runtime = loaded.runtime_type(
                    context=context,
                    config=config,
                    **injected,
                )
                api = create_api(
                    definition,
                    runtime,
                    composition_apis,
                    child_apis,
                )
            except ApplicationRuntimeError:
                raise
            except Exception as exc:
                raise ApplicationRuntimeError(
                    f"cannot create application runtime '{definition.id}': {exc}"
                ) from exc
            instance = ApplicationInstance(
                id=instance_id,
                definition_id=definition.id,
                module_id=definition.module_id,
                scope_id=owner_scope,
                root_instance_id=spec.id,
                parent_instance_id=parent_instance_id,
                runtime=runtime,
                api=api,
                context=context,
                compositions=composition_instances,
            )
            staged[instance_id] = instance
            return instance

        try:
            root = build(
                spec.use,
                spec.id,
                spec.config,
                spec.config_base_dir,
                None,
            )
        except Exception as exc:
            rollback_errors: list[BaseException] = []
            for scope_id, composition_id in reversed(created_compositions):
                try:
                    self._compositions.destroy_instance(scope_id, composition_id)
                # Runtime teardown is module-owned; preserve every rollback failure.
                except Exception as rollback_error:  # noqa: BLE001
                    rollback_errors.append(rollback_error)
            suffix = ""
            if rollback_errors:
                details = "; ".join(str(item) for item in rollback_errors)
                suffix = f"; rollback failures: {details}"
            raise ApplicationComponentError(
                f"cannot create application instance '{owner_scope}/{spec.id}': {exc}{suffix}"
            ) from exc

        for instance_id, instance in staged.items():
            self._instances[(owner_scope, instance_id)] = instance
        self._root_graphs[root_key] = tuple(staged)
        return root

    def destroy_instance(self, scope_id: str, instance_id: str) -> None:
        graph = self._require_root_graph(scope_id, instance_id)
        self._destroy_composition_graphs(scope_id, graph)
        self._discard_instance_graph(scope_id, instance_id)

    def _destroy_composition_graphs(
        self,
        scope_id: str,
        graph: tuple[str, ...],
    ) -> None:
        for graph_instance_id in reversed(graph):
            instance = self._instances[(scope_id, graph_instance_id)]
            composition_owner = f"application:{scope_id}:{graph_instance_id}"
            for composition_id in reversed(tuple(instance.compositions)):
                self._compositions.destroy_instance(composition_owner, composition_id)

    def _discard_instance_graph(self, scope_id: str, instance_id: str) -> None:
        graph = self._require_root_graph(scope_id, instance_id)
        for graph_instance_id in reversed(graph):
            del self._instances[(scope_id, graph_instance_id)]
        del self._root_graphs[(scope_id, instance_id)]

    def instances(self, *, scope_id: str | None = None) -> tuple[ApplicationInstance, ...]:
        values = (
            instance
            for (candidate_scope, _), instance in self._instances.items()
            if scope_id is None or candidate_scope == scope_id
        )
        return tuple(sorted(values, key=lambda item: (item.scope_id, item.id)))

    def require_instance(self, scope_id: str, instance_id: str) -> ApplicationInstance:
        try:
            return self._instances[(scope_id, instance_id)]
        except KeyError as exc:
            raise ApplicationComponentError(
                f"application instance not found: {scope_id}/{instance_id}"
            ) from exc

    def _require_root_graph(self, scope_id: str, instance_id: str) -> tuple[str, ...]:
        try:
            return self._root_graphs[(scope_id, instance_id)]
        except KeyError as exc:
            if (scope_id, instance_id) in self._instances:
                raise ApplicationComponentError(
                    f"operations require a root application instance: {scope_id}/{instance_id}"
                ) from exc
            raise ApplicationComponentError(
                f"application root instance not found: {scope_id}/{instance_id}"
            ) from exc

    def _stage_definitions(
        self,
        definitions: Sequence[ApplicationDefinition],
        *,
        artifact_digest: str,
        module: ModuleDescriptor,
    ) -> dict[str, LoadedApplicationDefinition]:
        imported: list[str] = []
        staged: dict[str, LoadedApplicationDefinition] = {}
        try:
            for definition in definitions:
                runtime_type, module_name = self._import_runtime(definition, artifact_digest)
                imported.append(module_name)
                staged[definition.id] = LoadedApplicationDefinition(
                    definition=definition,
                    runtime_type=runtime_type,
                    runtime_module_name=module_name,
                    module=module,
                )
        except Exception:
            for module_name in imported:
                self._remove_runtime_modules(module_name)
            raise
        return staged

    def _validate_staged_definitions(
        self,
        staged: Mapping[str, LoadedApplicationDefinition],
        staged_compositions: Mapping[str, LoadedCompositionDefinition],
    ) -> None:
        applications = {**self._definitions, **staged}
        for application_id in sorted(staged):
            self._validate_loaded_graph(
                application_id,
                applications,
                staged_compositions,
            )

    def _publish_definitions(self, staged: Mapping[str, LoadedApplicationDefinition]) -> None:
        self._definitions.update(staged)

    def _unpublish_definitions(self, definition_ids: Sequence[str]) -> None:
        for definition_id in definition_ids:
            self._definitions.pop(definition_id, None)

    def _discard_staged_definitions(
        self, staged: Mapping[str, LoadedApplicationDefinition]
    ) -> None:
        for loaded in staged.values():
            self._remove_runtime_modules(loaded.runtime_module_name)

    def _unload_blockers(
        self,
        module_id: str,
        owned_composition_ids: set[str],
        owned_application_ids: set[str],
    ) -> tuple[str, ...]:
        blockers: list[str] = []
        for application_id, candidate in sorted(self._definitions.items()):
            if application_id in owned_application_ids:
                continue
            for dependency in candidate.definition.compositions.values():
                if dependency.use in owned_composition_ids:
                    blockers.append(
                        "loaded application definition "
                        f"'{application_id}' requires composition '{dependency.use}' from "
                        f"module '{module_id}'"
                    )
            for dependency in candidate.definition.applications.values():
                if dependency.use in owned_application_ids:
                    blockers.append(
                        "loaded application definition "
                        f"'{application_id}' requires application '{dependency.use}' from "
                        f"module '{module_id}'"
                    )
        for graph_key, instance_ids in sorted(self._root_graphs.items()):
            root = self._instances[(graph_key[0], graph_key[1])]
            for instance_id in sorted(instance_ids):
                instance = self._instances[(graph_key[0], instance_id)]
                if instance.definition_id not in owned_application_ids:
                    continue
                blockers.append(
                    f"live application definition '{instance.definition_id}' from module "
                    f"'{module_id}': scope='{root.scope_id}', instance='{instance.id}', "
                    f"root='{root.id}'"
                )
        return tuple(sorted(set(blockers)))

    def _validate_loaded_graph(
        self,
        application_id: str,
        applications: Mapping[str, LoadedApplicationDefinition],
        staged_compositions: Mapping[str, LoadedCompositionDefinition],
    ) -> None:
        visiting: list[str] = []
        visited: set[str] = set()

        def visit(candidate_id: str) -> None:
            if candidate_id in visiting:
                start = visiting.index(candidate_id)
                cycle = (*visiting[start:], candidate_id)
                raise ApplicationComponentError(
                    f"application dependency cycle: {' -> '.join(cycle)}"
                )
            if candidate_id in visited:
                return
            try:
                loaded = applications[candidate_id]
            except KeyError as exc:
                raise ApplicationComponentError(
                    f"application definition is not loaded: {candidate_id}"
                ) from exc
            definition = loaded.definition
            visiting.append(candidate_id)
            for dependency in definition.compositions.values():
                if dependency.use not in staged_compositions:
                    self._compositions.require_definition(dependency.use)
            for dependency in definition.applications.values():
                visit(dependency.use)
            aliases = (*sorted(definition.compositions), *sorted(definition.applications))
            validate_runtime_constructor(loaded.runtime_type, aliases)
            visiting.pop()
            visited.add(candidate_id)

        visit(application_id)
        self._describe_function_graph(
            application_id,
            applications,
            staged_compositions,
        )

    def _describe_function_graph(
        self,
        application_id: str,
        applications: Mapping[str, LoadedApplicationDefinition],
        staged_compositions: Mapping[str, LoadedCompositionDefinition],
    ) -> dict[str, tuple[ApplicationFunctionDescriptor, ...]]:
        visited: set[str] = set()

        def collect(candidate_id: str) -> None:
            if candidate_id in visited:
                return
            definition = applications[candidate_id].definition
            for dependency in definition.applications.values():
                collect(dependency.use)
            visited.add(candidate_id)

        collect(application_id)
        descriptors = {
            candidate_id: describe_runtime_functions(
                applications[candidate_id].definition,
                applications[candidate_id].runtime_type,
            )
            for candidate_id in visited
        }
        application_functions = {
            candidate_id: {item.id for item in values}
            for candidate_id, values in descriptors.items()
        }
        for candidate_id, values in descriptors.items():
            definition = applications[candidate_id].definition
            for descriptor in values:
                if descriptor.origin is None:
                    continue
                alias, function_id = descriptor.origin.split(".", 1)
                if alias in definition.applications:
                    target = definition.applications[alias].use
                    target_functions = application_functions[target]
                else:
                    target = definition.compositions[alias].use
                    if target in staged_compositions:
                        loaded_composition = staged_compositions[target]
                        target_functions = {
                            item.id
                            for item in self._compositions._describe_candidate_functions(
                                loaded_composition
                            )
                        }
                    else:
                        target_functions = {
                            item.id
                            for item in self._compositions.describe_composition(target).functions
                        }
                if function_id not in target_functions:
                    raise ApplicationRuntimeError(
                        f"wrapper origin '{descriptor.origin}' in '{candidate_id}' refers to "
                        f"undeclared function '{target}.{function_id}'"
                    )
        return descriptors

    def _require_loaded_definition(self, application_id: str) -> LoadedApplicationDefinition:
        try:
            return self._definitions[application_id]
        except KeyError as exc:
            raise ApplicationComponentError(
                f"application definition is not loaded: {application_id}"
            ) from exc

    def _import_runtime(
        self,
        definition: ApplicationDefinition,
        artifact_digest: str,
    ) -> tuple[type[object], str]:
        safe_id = definition.id.replace("/", "_").replace("-", "_")
        module_name = f"_dix_application_{self._import_namespace}_{safe_id}_{artifact_digest[:16]}"
        if module_name in sys.modules:
            raise ApplicationComponentError(
                f"application runtime module name is already active: {definition.id}"
            )
        module_spec = importlib.util.spec_from_file_location(
            module_name,
            definition.runtime_path,
            submodule_search_locations=[str(definition.application_root)],
        )
        if module_spec is None or module_spec.loader is None:
            raise ApplicationComponentError(
                f"cannot create runtime import spec for application: {definition.id}"
            )
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        try:
            module_spec.loader.exec_module(module)
            runtime_type = getattr(module, "Runtime", None)
            if not inspect.isclass(runtime_type) or runtime_type.__module__ != module_name:
                raise ApplicationComponentError(
                    f"application '{definition.id}' must define runtime.py:Runtime"
                )
        except Exception:
            self._remove_runtime_modules(module_name)
            raise
        return runtime_type, module_name

    @staticmethod
    def _remove_runtime_modules(module_name: str) -> None:
        for active_name in tuple(sys.modules):
            if active_name == module_name or active_name.startswith(f"{module_name}."):
                sys.modules.pop(active_name, None)
