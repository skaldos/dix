from __future__ import annotations

from pathlib import Path

import pytest

from dix.registry import RegistryError, component_definitions, list_interfaces, load_interface


def test_component_definitions_include_core_components() -> None:
    ids = {definition.id for definition in component_definitions()}
    assert ids == {"input", "select"}


def test_load_interface_validates_component_refs(tmp_path: Path) -> None:
    path = tmp_path / "demo.toml"
    path.write_text(
        '[interface]\n'
        'id = "demo"\n'
        'title = "Demo"\n\n'
        '[[components]]\n'
        'id = "title"\n'
        'use = "input"\n'
        'config = { label = "Title" }\n\n'
        '[[components]]\n'
        'id = "kind"\n'
        'use = "select"\n'
        'config = { label = "Kind", mode = "single", options = [{ id = "a", label = "A" }] }\n'
    )
    spec = load_interface(path)
    assert spec.interface.id == "demo"
    assert [component.id for component in spec.components] == ["title", "kind"]


def test_load_interface_rejects_unknown_component(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text(
        '[interface]\n'
        'id = "bad"\n'
        'title = "Bad"\n\n'
        '[[components]]\n'
        'id = "x"\n'
        'use = "missing"\n'
    )
    with pytest.raises(RegistryError):
        load_interface(path)


def test_list_interfaces(tmp_path: Path) -> None:
    path = tmp_path / "demo.toml"
    path.write_text('[interface]\nid = "demo"\ntitle = "Demo"\n')
    specs = list_interfaces([tmp_path])
    assert [spec.interface.id for spec in specs] == ["demo"]
