from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dix.core.application import ApplicationComponent
from dix.core.composition import CompositionComponent
from dix.core.contract import ContractDefinition, ContractNotFound, ContractReference
from dix.core.model import ModelArtifactDefinition, ModelNotLoaded, ModelReference

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
        self._models: dict[ModelReference, ModelArtifactDefinition] = {}
        self._contracts: dict[ContractReference, ContractDefinition] = {}

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

        duplicate_models = sorted(
            {definition.reference for definition in inspection.model_definitions}
            & self._models.keys()
        )
        if duplicate_models:
            duplicate = duplicate_models[0]
            raise ModuleComponentError(
                f"model already loaded: {duplicate.use}@{duplicate.version!r}"
            )

        duplicate_contracts = sorted(
            {definition.reference for definition in inspection.contract_definitions}
            & self._contracts.keys()
        )
        if duplicate_contracts:
            duplicate = duplicate_contracts[0]
            raise ModuleComponentError(
                f"contract already loaded: {duplicate.use}@{duplicate.version!r}"
            )

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
            models=tuple(definition.reference for definition in inspection.model_definitions),
            contracts=tuple(definition.reference for definition in inspection.contract_definitions),
            composition_ids=tuple(sorted(item.id for item in inspection.composition_definitions)),
            application_ids=tuple(sorted(item.id for item in inspection.application_definitions)),
        )
        staged_compositions = {}
        staged_applications = {}
        published_compositions = False
        published_applications = False
        published_contracts = False
        published_models = False
        try:
            available_models = {
                **self._models,
                **{
                    definition.reference: definition
                    for definition in inspection.model_definitions
                },
            }
            for contract in inspection.contract_definitions:
                for reference in contract.model_references:
                    if reference not in available_models:
                        raise ModelNotLoaded(
                            f"model is not loaded: {reference.use}@{reference.version!r}"
                        )
            available_contracts = {
                **self._contracts,
                **{
                    definition.reference: definition
                    for definition in inspection.contract_definitions
                },
            }
            staged_compositions = self._compositions._stage_definitions(
                inspection.composition_definitions,
                artifact_digest=inspection.artifact_digest,
                module=descriptor,
                contracts=available_contracts,
                models=available_models,
            )
            staged_applications = self._applications._stage_definitions(
                inspection.application_definitions,
                artifact_digest=inspection.artifact_digest,
                module=descriptor,
                contracts=available_contracts,
                models=available_models,
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
            self._contracts.update(
                (definition.reference, definition)
                for definition in inspection.contract_definitions
            )
            published_contracts = True
            self._models.update(
                (definition.reference, definition)
                for definition in inspection.model_definitions
            )
            published_models = True
            loaded = LoadedModule(
                inspection=inspection,
                models={
                    definition.reference: definition
                    for definition in inspection.model_definitions
                },
                contracts={
                    definition.reference: definition
                    for definition in inspection.contract_definitions
                },
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
            if published_models:
                for definition in inspection.model_definitions:
                    self._models.pop(definition.reference, None)
            if published_contracts:
                for definition in inspection.contract_definitions:
                    self._contracts.pop(definition.reference, None)
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
        model_references = set(loaded.models)
        contract_references = set(loaded.contracts)
        model_blockers: list[str] = []
        for candidate in self._modules.values():
            if candidate.inspection.id == module_id:
                continue
            for contract in candidate.contracts.values():
                for reference in contract.model_references:
                    if reference in model_references:
                        model_blockers.append(
                            f"loaded contract '{contract.id}' from module "
                            f"'{candidate.inspection.id}' requires model "
                            f"'{reference.use}@{reference.version!r}' from module '{module_id}'"
                        )
        contract_blockers: list[str] = []
        for definition in self._compositions._definitions.values():
            if definition.definition.id in composition_ids:
                continue
            for function in definition.functions:
                if function.binding.contract.reference in contract_references:
                    contract_blockers.append(
                        f"loaded composition function '{definition.definition.id}."
                        f"{function.id}' requires contract "
                        f"'{function.binding.contract.id}' from module '{module_id}'"
                    )
        for definition in self._applications._definitions.values():
            if definition.definition.id in application_ids:
                continue
            for function in definition.functions:
                if function.binding.contract.reference in contract_references:
                    contract_blockers.append(
                        f"loaded application function '{definition.definition.id}."
                        f"{function.id}' requires contract "
                        f"'{function.binding.contract.id}' from module '{module_id}'"
                    )
        blockers = (
            *model_blockers,
            *contract_blockers,
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
        for reference in loaded.models:
            self._models.pop(reference, None)
        for reference in loaded.contracts:
            self._contracts.pop(reference, None)
        del self._modules[module_id]
        self._applications._discard_staged_definitions(loaded.applications)
        self._compositions._discard_staged_definitions(loaded.compositions)
        return loaded

    def modules(self) -> tuple[LoadedModule, ...]:
        return tuple(self._modules[item] for item in sorted(self._modules))

    def contracts(self) -> tuple[ContractDefinition, ...]:
        return tuple(self._contracts[reference] for reference in sorted(self._contracts))

    def models(self) -> tuple[ModelArtifactDefinition, ...]:
        return tuple(self._models[reference] for reference in sorted(self._models))

    def require_model(self, reference: ModelReference) -> ModelArtifactDefinition:
        try:
            return self._models[reference]
        except KeyError as exc:
            raise ModelNotLoaded(
                f"model is not loaded: {reference.use}@{reference.version!r}"
            ) from exc

    def require_contract(self, reference: ContractReference) -> ContractDefinition:
        try:
            return self._contracts[reference]
        except KeyError as exc:
            raise ContractNotFound(
                f"contract is not loaded: {reference.use}@{reference.version!r}"
            ) from exc

    def module_descriptors(self) -> tuple[ModuleDescriptor, ...]:
        return tuple(
            ModuleDescriptor(
                id=loaded.inspection.id,
                root=loaded.inspection.root,
                artifact_digest=loaded.inspection.artifact_digest,
                loaded=True,
                models=tuple(loaded.models),
                contracts=tuple(loaded.contracts),
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
