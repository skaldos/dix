from __future__ import annotations

from pathlib import Path

import pytest

from dix.config import load_effective_config, write_default_config


def test_effective_config_uses_defaults(tmp_path: Path) -> None:
    cfg = load_effective_config(cwd=tmp_path, paths=[], env={})
    assert cfg.values == {"composition": {"trusted_module_roots": [], "instance": []}}
    assert cfg.sources["composition"].source == "default"


def test_write_default_config(tmp_path: Path) -> None:
    path = tmp_path / "dix.toml"
    assert write_default_config(path) is True
    assert write_default_config(path) is False
    text = path.read_text()
    assert "trusted_module_roots" in text
    assert "interface_dirs" not in text
    assert "reference_renderer" not in text
    assert "host" not in text
    assert "port" not in text


def test_composition_config_resolves_roots_and_instance_base_from_source(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "dix.toml"
    config_path.write_text(
        """[composition]
trusted_module_roots = ["../modules-b", "../modules-a"]

[[composition.instance]]
id = "worker"
use = "acme/runtime/worker"
startup = true

[composition.instance.config]
relative_file = "data/input.json"

[[composition.instance]]
id = "disabled"
use = "acme/runtime/disabled"
startup = false
"""
    )

    cfg = load_effective_config(paths=[config_path], env={})

    assert cfg.composition.trusted_module_roots == (
        (tmp_path / "modules-b").resolve(),
        (tmp_path / "modules-a").resolve(),
    )
    assert [item.id for item in cfg.composition.instances] == ["worker", "disabled"]
    assert cfg.composition.instances[0].config == {"relative_file": "data/input.json"}
    assert cfg.composition.instances[0].config_base_dir == config_dir.resolve()
    assert cfg.sources["composition"].detail == str(config_path)


def test_composition_config_rejects_duplicate_instances_before_use(tmp_path: Path) -> None:
    config_path = tmp_path / "dix.toml"
    config_path.write_text(
        """[composition]
[[composition.instance]]
id = "same"
use = "acme/one/item"
[[composition.instance]]
id = "same"
use = "acme/two/item"
"""
    )

    with pytest.raises(ValueError, match="duplicate composition instance id"):
        load_effective_config(paths=[config_path], env={})
