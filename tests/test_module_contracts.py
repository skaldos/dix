from __future__ import annotations

from pathlib import Path

import pytest

from dix.core import (
    ContractNotFound,
    ContractReference,
    ModuleComponent,
    ModuleComponentError,
    create_core_component_registry,
)


def contract_module(root: Path, *, version: str | None = "1") -> Path:
    path = root / "contracts" / "echo" / "contract.toml"
    path.parent.mkdir(parents=True)
    version_line = "" if version is None else f'version = "{version}"\n'
    path.write_text(
        '[contract]\n'
        'id = "echo"\n'
        f'{version_line}\n'
        '[input]\n'
        'type = "string"\n\n'
        '[output]\n'
        'type = "string"\n'
    )
    return root


def module_component() -> ModuleComponent:
    registry = create_core_component_registry()
    return registry.require("module", ModuleComponent)


def test_contract_only_module_loads_describes_and_unloads(tmp_path: Path) -> None:
    modules = module_component()
    root = contract_module(tmp_path / "module")

    inspection = modules.inspect_module(root, module_id="acme/contracts")
    assert [item.id for item in inspection.contract_definitions] == ["acme/contracts/echo"]

    loaded = modules.load_module(root, module_id="acme/contracts")
    reference = ContractReference("acme/contracts/echo", "1")
    assert loaded.contracts[reference].strand.input_element.type == "string"
    assert modules.require_contract(reference).id == "acme/contracts/echo"
    assert modules.module_descriptors()[0].contracts == (reference,)

    modules.unload_module("acme/contracts")
    with pytest.raises(ContractNotFound):
        modules.require_contract(reference)


def test_contract_version_resolution_is_exact(tmp_path: Path) -> None:
    modules = module_component()
    modules.load_module(contract_module(tmp_path / "module"), module_id="acme/contracts")

    with pytest.raises(ContractNotFound):
        modules.require_contract(ContractReference("acme/contracts/echo", None))


def test_duplicate_contract_module_is_rejected_without_partial_publication(
    tmp_path: Path,
) -> None:
    modules = module_component()
    modules.load_module(contract_module(tmp_path / "first"), module_id="acme/contracts")

    with pytest.raises(ModuleComponentError, match="module already loaded"):
        modules.load_module(contract_module(tmp_path / "second"), module_id="acme/contracts")

    assert len(modules.contracts()) == 1
    assert len(modules.modules()) == 1
