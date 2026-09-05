from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from dix.core.composition.models import CompositionDependencySpec


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
