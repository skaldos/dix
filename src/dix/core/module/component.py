from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dix.core.application import ApplicationComponent
from dix.core.composition import CompositionComponent

from .inspection import discover_modules, inspect_module
from .models import LoadedModule, ModuleDescriptor, ModuleInspection


class ModuleComponentError(Exception):
    """Raised when a module cannot be published or removed atomically."""


class ModuleComponent:
    """Authoritative runtime registry for loaded mixed module bundles."""

    component_id = "module"

    def __init__(
        self,
        *,
        compositions: CompositionComponent,
        applications: ApplicationComponent,
    ) -> None:
        self._compositions = compositions
        self._applications = applications
        self._modules: dict[str, LoadedModule] = {}

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
        """Stage, validate, and publish every definition in one module together."""
        inspection = inspect_module(root, module_id=module_id)
        if (
            expected_artifact_digest is not None
            and inspection.artifact_digest != expected_artifact_digest
        ):
            raise ModuleComponentError(
                f"module artifact digest mismatch for '{inspection.id}': "
                f"expected {expected_artifact_digest}, got {inspection.artifact_digest}"
            )
        if inspection.id in self._modules:
            raise ModuleComponentError(f"module already loaded: {inspection.id}")

        loaded_composition_ids = {item.id for item in self._compositions.definitions()}
        loaded_application_ids = {item.id for item in self._applications.definitions()}
        duplicate_compositions = sorted(
            definition.id
            for definition in inspection.composition_definitions
            if definition.id in loaded_composition_ids
        )
        if duplicate_compositions:
            raise ModuleComponentError(
                f"composition definition already loaded: {duplicate_compositions[0]}"
            )
        duplicate_applications = sorted(
            definition.id
            for definition in inspection.application_definitions
            if definition.id in loaded_application_ids
        )
        if duplicate_applications:
            raise ModuleComponentError(
                f"application definition already loaded: {duplicate_applications[0]}"
            )

        descriptor = ModuleDescriptor(
            id=inspection.id,
            root=inspection.root,
            artifact_digest=inspection.artifact_digest,
            loaded=True,
            composition_ids=tuple(sorted(item.id for item in inspection.composition_definitions)),
            application_ids=tuple(sorted(item.id for item in inspection.application_definitions)),
        )
        staged_compositions = {}
        staged_applications = {}
        published_compositions = False
        published_applications = False
        try:
            staged_compositions = self._compositions._stage_definitions(
                inspection.composition_definitions,
                artifact_digest=inspection.artifact_digest,
                module=descriptor,
            )
            staged_applications = self._applications._stage_definitions(
                inspection.application_definitions,
                artifact_digest=inspection.artifact_digest,
                module=descriptor,
            )
            self._compositions._validate_staged_definitions(staged_compositions)
            self._applications._validate_staged_definitions(
                staged_applications,
                staged_compositions,
            )
            self._compositions._publish_definitions(staged_compositions)
            published_compositions = True
            self._applications._publish_definitions(staged_applications)
            published_applications = True
            loaded = LoadedModule(
                inspection=inspection,
                compositions={
                    item: staged_compositions[item] for item in sorted(staged_compositions)
                },
                applications={
                    item: staged_applications[item] for item in sorted(staged_applications)
                },
            )
            self._modules[inspection.id] = loaded
            return loaded
        except Exception as exc:
            if published_applications:
                self._applications._unpublish_definitions(tuple(staged_applications))
            if published_compositions:
                self._compositions._unpublish_definitions(tuple(staged_compositions))
            self._applications._discard_staged_definitions(staged_applications)
            self._compositions._discard_staged_definitions(staged_compositions)
            if isinstance(exc, ModuleComponentError):
                raise
            raise ModuleComponentError(f"cannot load module '{inspection.id}': {exc}") from exc

    def unload_module(self, module_id: str) -> LoadedModule:
        """Remove one module only after all definition and instance uses are gone."""
        loaded = self.require_module(module_id)
        composition_ids = set(loaded.compositions)
        application_ids = set(loaded.applications)
        blockers = (
            *self._compositions._unload_blockers(module_id, composition_ids),
            *self._applications._unload_blockers(
                module_id,
                composition_ids,
                application_ids,
            ),
        )
        if blockers:
            details = "\n".join(f"- {item}" for item in sorted(blockers))
            raise ModuleComponentError(
                f"module '{module_id}' cannot be unloaded while it is in use:\n{details}"
            )

        self._applications._unpublish_definitions(tuple(application_ids))
        self._compositions._unpublish_definitions(tuple(composition_ids))
        del self._modules[module_id]
        self._applications._discard_staged_definitions(loaded.applications)
        self._compositions._discard_staged_definitions(loaded.compositions)
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
                application_ids=tuple(sorted(loaded.applications)),
            )
            for loaded in self.modules()
        )

    def require_module(self, module_id: str) -> LoadedModule:
        try:
            return self._modules[module_id]
        except KeyError as exc:
            raise ModuleComponentError(f"module is not loaded: {module_id}") from exc
