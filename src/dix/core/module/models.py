from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dix.core.application.models import ApplicationDefinition
    from dix.core.composition.models import CompositionDefinition


@dataclass(frozen=True)
class ModuleInspection:
    id: str
    root: Path
    artifact_digest: str
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
