from __future__ import annotations

from pathlib import Path

import pytest

from dix.core import ModuleComponent, create_core_component_registry
from dix.modules import FirstPartyModuleError, first_party_module_path

REPOSITORY = Path(__file__).resolve().parents[1]


def test_cli_module_is_explicitly_resolvable_and_loadable_from_source() -> None:
    source = first_party_module_path("dix/cli")
    assert source == (REPOSITORY / "modules" / "dix" / "cli").resolve()

    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    loaded = modules.load_module(source, module_id="dix/cli")

    assert tuple(loaded.compositions) == ("dix/cli/typer",)
    assert tuple(loaded.applications) == ()
    modules.unload_module("dix/cli")


@pytest.mark.parametrize("module_id", ["", "../cli", "dix//cli", "/dix/cli"])
def test_first_party_module_resolution_rejects_invalid_ids(module_id: str) -> None:
    with pytest.raises(FirstPartyModuleError, match="invalid first-party module id"):
        first_party_module_path(module_id)


def test_unknown_first_party_module_is_not_discovered() -> None:
    with pytest.raises(FirstPartyModuleError, match="is not available"):
        first_party_module_path("acme/unknown")
