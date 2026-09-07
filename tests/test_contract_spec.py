from __future__ import annotations

from pathlib import Path

import pytest

from dix.core.contract import ContractSpecError, inspect_contract_spec


def write_contract(root: Path, body: str) -> Path:
    path = root / "contracts" / "echo" / "contract.toml"
    path.parent.mkdir(parents=True)
    path.write_text(body)
    return path


def valid_contract() -> str:
    return (
        '[contract]\n'
        'id = "echo"\n'
        'version = "1"\n\n'
        '[input]\n'
        'type = "string"\n\n'
        '[output]\n'
        'type = "string"\n'
    )


def test_contract_spec_is_code_free_and_normalized(tmp_path: Path) -> None:
    definition = inspect_contract_spec(
        write_contract(tmp_path, valid_contract()),
        module_id="acme/contracts",
    )

    assert definition.id == "acme/contracts/echo"
    assert definition.local_id == "echo"
    assert definition.module_id == "acme/contracts"
    assert definition.version == "1"
    assert definition.reference.use == "acme/contracts/echo"
    assert definition.reference.version == "1"
    assert definition.strand.id == definition.id
    assert definition.strand.input_element.type == "string"
    assert definition.strand.output_element.type == "string"


def test_contract_spec_rejects_unknown_element_type(tmp_path: Path) -> None:
    body = valid_contract().replace('type = "string"', 'type = "custom"', 1)

    with pytest.raises(ContractSpecError, match="not a core element type"):
        inspect_contract_spec(write_contract(tmp_path, body), module_id="acme/contracts")


def test_contract_spec_id_must_match_directory(tmp_path: Path) -> None:
    body = valid_contract().replace('id = "echo"', 'id = "other"')

    with pytest.raises(ContractSpecError, match="does not match directory"):
        inspect_contract_spec(write_contract(tmp_path, body), module_id="acme/contracts")
