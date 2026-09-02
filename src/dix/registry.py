from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import ValidationError

from dix.components import get_core_components
from dix.models import ComponentDefinition, InterfaceSpec


class RegistryError(Exception):
    pass


class InterfaceNotFound(RegistryError):
    pass


def load_interface(path: Path) -> InterfaceSpec:
    try:
        raw = tomllib.loads(path.read_text())
        spec = InterfaceSpec.model_validate({**raw, "source": str(path)})
    except (OSError, tomllib.TOMLDecodeError, ValidationError, ValueError) as e:
        raise RegistryError(f"invalid interface spec {path}: {e}") from e
    validate_component_refs(spec)
    return spec


def interface_paths(interface_dirs: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for directory in interface_dirs:
        if directory.exists():
            paths.extend(sorted(directory.glob("*.toml")))
    return sorted(paths)


def list_interfaces(interface_dirs: list[Path]) -> list[InterfaceSpec]:
    return [load_interface(path) for path in interface_paths(interface_dirs)]


def find_interface(interface_dirs: list[Path], interface_id: str) -> InterfaceSpec:
    for path in interface_paths(interface_dirs):
        if path.stem == interface_id:
            return load_interface(path)
        try:
            spec = load_interface(path)
        except RegistryError:
            continue
        if spec.interface.id == interface_id:
            return spec
    raise InterfaceNotFound(interface_id)


def component_definitions() -> list[ComponentDefinition]:
    return [component.definition for component in get_core_components().values()]


def validate_component_refs(spec: InterfaceSpec) -> None:
    components = get_core_components()
    for component in spec.components:
        if component.use not in components:
            raise RegistryError(f"unknown component '{component.use}' in interface '{spec.interface.id}'")
        components[component.use].create_runtime(component)
