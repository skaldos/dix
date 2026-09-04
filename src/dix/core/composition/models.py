from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping


def _immutable_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class CompositionDependencySpec:
    use: str
    config: Mapping[str, Any] = field(default_factory=dict)
    export: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "config", _immutable_mapping(self.config))
        object.__setattr__(self, "export", tuple(self.export))


@dataclass(frozen=True)
class CompositionFunctionSpec:
    description: str | None = None
    export: str | None = None


@dataclass(frozen=True)
class CompositionDefinition:
    id: str
    local_id: str
    module_id: str
    module_root: Path
    composition_root: Path
    spec_path: Path
    runtime_path: Path
    components: Mapping[str, str] = field(default_factory=dict)
    compositions: Mapping[str, CompositionDependencySpec] = field(default_factory=dict)
    functions: Mapping[str, CompositionFunctionSpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "components", MappingProxyType(dict(self.components)))
        object.__setattr__(self, "compositions", MappingProxyType(dict(self.compositions)))
        object.__setattr__(self, "functions", MappingProxyType(dict(self.functions)))


@dataclass(frozen=True)
class ModuleInspection:
    id: str
    root: Path
    artifact_digest: str
    definitions: tuple[CompositionDefinition, ...]


@dataclass(frozen=True)
class LoadedCompositionDefinition:
    definition: CompositionDefinition
    runtime_type: type[object]
    runtime_module_name: str


@dataclass(frozen=True)
class LoadedModule:
    inspection: ModuleInspection
    compositions: Mapping[str, LoadedCompositionDefinition]

    def __post_init__(self) -> None:
        object.__setattr__(self, "compositions", MappingProxyType(dict(self.compositions)))


@dataclass(frozen=True)
class ModuleDescriptor:
    id: str
    root: Path
    artifact_digest: str
    loaded: bool
    composition_ids: tuple[str, ...]


@dataclass(frozen=True)
class CompositionDependencyEdge:
    source: str
    alias: str
    target: str
    kind: Literal["component", "composition"]


@dataclass(frozen=True)
class CompositionDependencyGraph:
    root: str
    nodes: tuple[str, ...]
    edges: tuple[CompositionDependencyEdge, ...]
