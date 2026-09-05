from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from dix.core.module.models import ModuleDescriptor

    from .runtime import CompositionApi


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
class CompositionSource:
    local_id: str
    module_root: Path
    composition_root: Path
    spec_path: Path
    components: Mapping[str, str] = field(default_factory=dict)
    compositions: Mapping[str, CompositionDependencySpec] = field(default_factory=dict)
    functions: Mapping[str, CompositionFunctionSpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "components", MappingProxyType(dict(self.components)))
        object.__setattr__(self, "compositions", MappingProxyType(dict(self.compositions)))
        object.__setattr__(self, "functions", MappingProxyType(dict(self.functions)))


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
class LoadedCompositionDefinition:
    definition: CompositionDefinition
    runtime_type: type[object]
    runtime_module_name: str
    module: ModuleDescriptor


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


@dataclass(frozen=True)
class CompositionRuntimeContext:
    instance_id: str
    composition_id: str
    module_id: str
    module_root: Path
    composition_root: Path
    config_base_dir: Path
    owner_scope_id: str


@dataclass(frozen=True)
class CompositionInstanceSpec:
    id: str
    use: str
    config: Mapping[str, Any]
    config_base_dir: Path
    startup: bool = False

    def __post_init__(self) -> None:
        instance_id = self.id.strip()
        if not instance_id:
            raise ValueError("composition instance id must not be empty")
        object.__setattr__(self, "id", instance_id)
        object.__setattr__(self, "config", _immutable_mapping(self.config))
        object.__setattr__(self, "config_base_dir", self.config_base_dir.expanduser().resolve())


@dataclass(frozen=True)
class CompositionFunctionDescriptor:
    id: str
    composition_id: str
    source: Literal["local", "local_wrapper"]
    origin: str | None
    signature: inspect.Signature
    return_annotation: object
    docstring: str | None
    is_async: bool = False


@dataclass(frozen=True)
class CompositionDescriptor:
    definition: CompositionDefinition
    functions: tuple[CompositionFunctionDescriptor, ...]
    module: ModuleDescriptor


@dataclass
class CompositionInstance:
    id: str
    definition_id: str
    module_id: str
    scope_id: str
    root_instance_id: str
    parent_instance_id: str | None
    runtime: object
    api: CompositionApi
    context: CompositionRuntimeContext
    state: Literal["created", "initialized", "cleaned"] = "created"
