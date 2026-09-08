from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path

from dix.core.element import CORE_ELEMENT_TYPES, ElementSpec
from dix.core.model import ModelReference
from dix.core.module.errors import ModuleSpecError
from dix.core.module.validation import canonical_file, normalize_local_id, normalize_module_id
from dix.core.norn import StrandDefinition

from .errors import ContractSpecError
from .models import ContractDefinition


def inspect_contract_spec(path: Path, *, module_id: str) -> ContractDefinition:
    """Parse one code-free contract artifact into an immutable strand definition."""
    normalized_module_id = normalize_module_id(module_id)
    spec_path = canonical_file(path, label="contract spec")
    if spec_path.name != "contract.toml":
        raise ContractSpecError(f"contract spec must be named contract.toml: {spec_path}")
    contract_root = spec_path.parent
    contracts_root = contract_root.parent
    if contracts_root.name != "contracts":
        raise ContractSpecError(
            f"contract spec must be directly below a contracts directory: {spec_path}"
        )
    try:
        raw = tomllib.loads(spec_path.read_text())
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ContractSpecError(f"cannot read contract spec {spec_path}: {exc}") from exc
    _reject_unknown(raw, {"contract", "input", "output"}, "contract spec")

    header = _mapping(raw.get("contract"), "contract")
    _reject_unknown(header, {"id", "version"}, "contract")
    local_id = normalize_local_id(_string(header.get("id"), "contract.id"), artifact="contract")
    if local_id != contract_root.name:
        raise ContractSpecError(
            f"contract.id '{local_id}' does not match directory '{contract_root.name}'"
        )
    version = header.get("version")
    if version is not None:
        version = _string(version, "contract.version")

    contract_id = f"{normalized_module_id}/{local_id}"
    strand = StrandDefinition(
        id=contract_id,
        input_element=_element(raw.get("input"), "input"),
        output_element=_element(raw.get("output"), "output"),
    )
    return ContractDefinition(
        id=contract_id,
        local_id=local_id,
        module_id=normalized_module_id,
        version=version,
        strand=strand,
        spec_path=spec_path,
    )


def _element(raw: object, label: str) -> ElementSpec:
    value = _mapping(raw, label)
    _reject_unknown(value, {"type", "config", "use", "version"}, label)
    type_name = _string(value.get("type"), f"{label}.type")
    if type_name == "model":
        if "config" in value:
            raise ContractSpecError(f"{label}.config is not allowed for a model reference")
        use = _string(value.get("use"), f"{label}.use")
        version = value.get("version")
        if version is not None:
            version = _string(version, f"{label}.version")
        try:
            reference = ModelReference(use, version)
        except ValueError as exc:
            raise ContractSpecError(f"invalid {label} model reference: {exc}") from exc
        return ElementSpec("model", {"reference": reference})
    if "use" in value or "version" in value:
        raise ContractSpecError(
            f"{label}.use and {label}.version require type = 'model'"
        )
    if type_name not in CORE_ELEMENT_TYPES and "/" not in type_name:
        raise ContractSpecError(
            f"{label}.type must be a core type or namespaced custom type: {type_name}"
        )
    if type_name not in CORE_ELEMENT_TYPES:
        try:
            type_name = normalize_module_id(type_name)
        except ModuleSpecError as exc:
            raise ContractSpecError(f"invalid {label}.type: {exc}") from exc
    config = _mapping(value.get("config", {}), f"{label}.config")
    return ElementSpec(type_name, config)


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ContractSpecError(f"{label} must be a table")
    return dict(value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractSpecError(f"{label} must be a non-empty string")
    return value.strip()


def _reject_unknown(value: Mapping[str, object], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ContractSpecError(f"unknown {label} key: {unknown[0]}")
