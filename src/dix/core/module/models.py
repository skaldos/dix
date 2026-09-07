from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dix.core.application.models import ApplicationDefinition, LoadedApplicationDefinition
    from dix.core.composition.models import CompositionDefinition, LoadedCompositionDefinition
    from dix.core.contract import ContractDefinition, ContractReference


@dataclass(frozen=True)
class ModuleInspection:
    id: str
    root: Path
    artifact_digest: str
    contract_definitions: tuple[ContractDefinition, ...]
    composition_definitions: tuple[CompositionDefinition, ...]
    application_definitions: tuple[ApplicationDefinition, ...]


@dataclass(frozen=True)
class ModuleDescriptor:
    id: str
    root: Path
    artifact_digest: str
    loaded: bool
    composition_ids: tuple[str, ...]
    application_ids: tuple[str, ...]
    contracts: tuple[ContractReference, ...] = ()


@dataclass(frozen=True)
class LoadedModule:
    inspection: ModuleInspection
    contracts: Mapping[ContractReference, ContractDefinition]
    compositions: Mapping[str, LoadedCompositionDefinition]
    applications: Mapping[str, LoadedApplicationDefinition]

    def __post_init__(self) -> None:
        object.__setattr__(self, "contracts", MappingProxyType(dict(self.contracts)))
        object.__setattr__(self, "compositions", MappingProxyType(dict(self.compositions)))
        object.__setattr__(self, "applications", MappingProxyType(dict(self.applications)))
