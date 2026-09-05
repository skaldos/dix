from __future__ import annotations

from dataclasses import dataclass

from dix.config import CompositionSettings
from dix.core import (
    ComponentRegistry,
    CompositionComponent,
    ModuleComponent,
    create_core_component_registry,
)
from dix.core.composition import CompositionComponentError, CompositionInstanceSpec
from dix.core.module import ModuleInspection


class CompositionAssemblyError(Exception):
    """Raised when configured composition modules cannot be assembled atomically."""


@dataclass(frozen=True)
class CompositionAssembly:
    components: ComponentRegistry
    modules: ModuleComponent
    compositions: CompositionComponent

    def shutdown(self) -> None:
        """Destroy every root graph owned by this assembly."""
        roots = [
            instance
            for instance in self.compositions.instances()
            if instance.parent_instance_id is None
        ]
        errors: list[BaseException] = []
        for instance in reversed(roots):
            try:
                self.compositions.destroy_instance(instance.scope_id, instance.id)
            except Exception as exc:
                errors.append(exc)
        if errors:
            details = "; ".join(f"{type(item).__name__}: {item}" for item in errors)
            raise CompositionAssemblyError(f"composition assembly shutdown failed: {details}")


def assemble_compositions(settings: CompositionSettings) -> CompositionAssembly:
    """Validate, load, and construct the configured trusted composition graph."""
    components = create_core_component_registry()
    modules = components.require("module", ModuleComponent)
    compositions = components.require("composition", CompositionComponent)
    inspections = modules.discover_modules(settings.trusted_module_roots)
    composition_definitions = {
        definition.id: definition
        for inspection in inspections
        for definition in inspection.composition_definitions
    }
    application_definitions = {
        definition.id: definition
        for inspection in inspections
        for definition in inspection.application_definitions
    }

    for instance in settings.instances:
        if instance.use not in composition_definitions:
            raise CompositionAssemblyError(
                f"configured composition is not present in trusted roots: {instance.use}"
            )
    _validate_definition_graphs(
        composition_definitions,
        application_definitions,
        components,
    )
    for inspection in _module_load_order(inspections):
        modules.load_module(
            inspection.root,
            module_id=inspection.id,
            expected_artifact_digest=inspection.artifact_digest,
        )

    created: list[str] = []
    try:
        for configured in settings.instances:
            if not configured.startup:
                continue
            compositions.create_instance(
                CompositionInstanceSpec(
                    id=configured.id,
                    use=configured.use,
                    config=configured.config,
                    config_base_dir=configured.config_base_dir,
                ),
                owner_scope_id="startup",
            )
            created.append(configured.id)
    except Exception as exc:
        cleanup_errors: list[Exception] = []
        for instance_id in reversed(created):
            try:
                compositions.require_instance("startup", instance_id)
            except CompositionComponentError:
                continue
            try:
                compositions.destroy_instance("startup", instance_id)
            except Exception as cleanup_error:
                cleanup_errors.append(cleanup_error)
        details = "; ".join(str(item) for item in cleanup_errors)
        suffix = f"; cleanup failures: {details}" if details else ""
        raise CompositionAssemblyError(f"composition startup failed: {exc}{suffix}") from exc
    return CompositionAssembly(
        components=components,
        modules=modules,
        compositions=compositions,
    )


def _validate_definition_graphs(
    composition_definitions,
    application_definitions,
    components: ComponentRegistry,
) -> None:
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(definition_id: str) -> None:
        if definition_id in visiting:
            start = visiting.index(definition_id)
            cycle = (*visiting[start:], definition_id)
            raise CompositionAssemblyError(f"composition dependency cycle: {' -> '.join(cycle)}")
        if definition_id in visited:
            return
        definition = composition_definitions[definition_id]
        visiting.append(definition_id)
        for component_id in definition.components.values():
            try:
                components.require_provider(component_id)
            except Exception as exc:
                raise CompositionAssemblyError(
                    f"unknown component '{component_id}' in composition '{definition_id}'"
                ) from exc
        for dependency in definition.compositions.values():
            if dependency.use not in composition_definitions:
                raise CompositionAssemblyError(
                    f"unknown composition dependency '{dependency.use}' in '{definition_id}'"
                )
            visit(dependency.use)
        visiting.pop()
        visited.add(definition_id)

    for definition_id in sorted(composition_definitions):
        visit(definition_id)

    visiting_apps: list[str] = []
    visited_apps: set[str] = set()

    def visit_app(definition_id: str) -> None:
        if definition_id in visiting_apps:
            start = visiting_apps.index(definition_id)
            cycle = (*visiting_apps[start:], definition_id)
            raise CompositionAssemblyError(f"application dependency cycle: {' -> '.join(cycle)}")
        if definition_id in visited_apps:
            return
        definition = application_definitions[definition_id]
        visiting_apps.append(definition_id)
        for dependency in definition.compositions.values():
            if dependency.use not in composition_definitions:
                raise CompositionAssemblyError(
                    f"unknown composition dependency '{dependency.use}' in "
                    f"application '{definition_id}'"
                )
        for dependency in definition.applications.values():
            if dependency.use not in application_definitions:
                raise CompositionAssemblyError(
                    f"unknown application dependency '{dependency.use}' in '{definition_id}'"
                )
            visit_app(dependency.use)
        visiting_apps.pop()
        visited_apps.add(definition_id)

    for definition_id in sorted(application_definitions):
        visit_app(definition_id)


def _module_load_order(inspections: tuple[ModuleInspection, ...]) -> tuple[ModuleInspection, ...]:
    by_id = {item.id: item for item in inspections}
    composition_modules = {
        definition.id: inspection.id
        for inspection in inspections
        for definition in inspection.composition_definitions
    }
    application_modules = {
        definition.id: inspection.id
        for inspection in inspections
        for definition in inspection.application_definitions
    }
    dependencies: dict[str, set[str]] = {item.id: set() for item in inspections}
    for inspection in inspections:
        for definition in inspection.composition_definitions:
            for dependency in definition.compositions.values():
                target_module = composition_modules[dependency.use]
                if target_module != inspection.id:
                    dependencies[inspection.id].add(target_module)
        for definition in inspection.application_definitions:
            for dependency in definition.compositions.values():
                target_module = composition_modules[dependency.use]
                if target_module != inspection.id:
                    dependencies[inspection.id].add(target_module)
            for dependency in definition.applications.values():
                target_module = application_modules[dependency.use]
                if target_module != inspection.id:
                    dependencies[inspection.id].add(target_module)
    ordered: list[ModuleInspection] = []
    remaining = {key: set(value) for key, value in dependencies.items()}
    while remaining:
        ready = sorted(key for key, value in remaining.items() if not value)
        if not ready:
            raise CompositionAssemblyError("module dependency graph contains a cycle")
        for module_id in ready:
            ordered.append(by_id[module_id])
            del remaining[module_id]
        for value in remaining.values():
            value.difference_update(ready)
    return tuple(ordered)
