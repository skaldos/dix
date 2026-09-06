from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from dix.core.composition.models import CompositionDependencySpec
from dix.core.function import FunctionContract

if TYPE_CHECKING:
    from dix.core.composition.models import CompositionInstance
    from dix.core.module.models import ModuleDescriptor

    from .runtime import ApplicationApi


def _immutable_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class ApplicationDependencySpec:
    use: str
    config: Mapping[str, Any] = field(default_factory=dict)
    export: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "config", _immutable_mapping(self.config))
        object.__setattr__(self, "export", tuple(self.export))


@dataclass(frozen=True)
class ApplicationFunctionSpec:
    description: str | None = None
    export: str | None = None


@dataclass(frozen=True)
class ApplicationSource:
    local_id: str
    module_root: Path
    application_root: Path
    spec_path: Path
    compositions: Mapping[str, CompositionDependencySpec] = field(default_factory=dict)
    applications: Mapping[str, ApplicationDependencySpec] = field(default_factory=dict)
    functions: Mapping[str, ApplicationFunctionSpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "compositions", MappingProxyType(dict(self.compositions)))
        object.__setattr__(self, "applications", MappingProxyType(dict(self.applications)))
        object.__setattr__(self, "functions", MappingProxyType(dict(self.functions)))


@dataclass(frozen=True)
class ApplicationDefinition:
    id: str
    local_id: str
    module_id: str
    module_root: Path
    application_root: Path
    spec_path: Path
    runtime_path: Path
    compositions: Mapping[str, CompositionDependencySpec] = field(default_factory=dict)
    applications: Mapping[str, ApplicationDependencySpec] = field(default_factory=dict)
    functions: Mapping[str, ApplicationFunctionSpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "compositions", MappingProxyType(dict(self.compositions)))
        object.__setattr__(self, "applications", MappingProxyType(dict(self.applications)))
        object.__setattr__(self, "functions", MappingProxyType(dict(self.functions)))


@dataclass(frozen=True)
class LoadedApplicationDefinition:
    definition: ApplicationDefinition
    runtime_type: type[object]
    runtime_module_name: str
    module: ModuleDescriptor
    functions: tuple[ApplicationFunctionDescriptor, ...]


@dataclass(frozen=True)
class ApplicationDependencyEdge:
    source: str
    alias: str
    target: str
    kind: Literal["composition", "application"]


@dataclass(frozen=True)
class ApplicationDependencyGraph:
    root: str
    nodes: tuple[str, ...]
    edges: tuple[ApplicationDependencyEdge, ...]


@dataclass(frozen=True)
class ApplicationFunctionDescriptor:
    id: str
    application_id: str
    source: Literal["local", "local_wrapper"]
    origin: str | None
    signature: inspect.Signature
    return_annotation: object
    docstring: str | None
    contract: FunctionContract
    is_async: bool = False


@dataclass(frozen=True)
class ApplicationDescriptor:
    definition: ApplicationDefinition
    functions: tuple[ApplicationFunctionDescriptor, ...]
    module: ModuleDescriptor


@dataclass(frozen=True)
class ApplicationRuntimeContext:
    instance_id: str
    application_id: str
    module_id: str
    module_root: Path
    application_root: Path
    config_base_dir: Path
    owner_scope_id: str


@dataclass(frozen=True)
class ApplicationInstanceSpec:
    id: str
    use: str
    config: Mapping[str, Any]
    config_base_dir: Path

    def __post_init__(self) -> None:
        instance_id = self.id.strip()
        if not instance_id:
            raise ValueError("application instance id must not be empty")
        object.__setattr__(self, "id", instance_id)
        object.__setattr__(self, "config", _immutable_mapping(self.config))
        object.__setattr__(
            self,
            "config_base_dir",
            self.config_base_dir.expanduser().resolve(),
        )


@dataclass
class ApplicationInstance:
    id: str
    definition_id: str
    module_id: str
    scope_id: str
    root_instance_id: str
    parent_instance_id: str | None
    runtime: object
    api: ApplicationApi
    context: ApplicationRuntimeContext
    compositions: Mapping[str, CompositionInstance]
    def __post_init__(self) -> None:
        self.compositions = MappingProxyType(dict(self.compositions))
