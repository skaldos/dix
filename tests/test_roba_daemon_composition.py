from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from dix.core import CompositionComponent, ModuleComponent, create_core_component_registry
from dix.core.composition import CompositionInstanceSpec
from dix.modules import first_party_module_path


def _instance(tmp_path: Path):
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    compositions = registry.require("composition", CompositionComponent)
    modules.load_module(first_party_module_path("dix/state"), module_id="dix/state")
    modules.load_module(first_party_module_path("dix/roba"), module_id="dix/roba")
    return compositions.create_instance(
        CompositionInstanceSpec("daemon", "dix/roba/daemon", {}, tmp_path),
        owner_scope_id="test",
    )


def test_real_roba_daemon_lifecycle_uses_one_exported_local_config(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    get = instance.api.require("get")
    set_value = instance.api.require("set")
    start = instance.api.require("start")
    status = instance.api.require("status")
    stop = instance.api.require("stop")
    config = {
        "daemon_id": "composition-test",
        "runtime_root": str(tmp_path / "runtime"),
        "logs_root": str(tmp_path / "logs"),
        "timeout": 5.0,
    }
    assert set_value(config) is True
    assert get() == config
    creation = start()
    creation_data = asdict(creation)
    token = creation_data.pop("control_token")
    try:
        assert {item.id for item in instance.api.functions()} == {
            "get", "set", "start", "status", "stop"
        }
        assert isinstance(token, str) and token
        assert creation_data["daemon_id"] == "composition-test"
        assert status()["daemon_id"] == "composition-test"
        assert (tmp_path / "runtime" / "daemons" / "composition-test").is_dir()
        assert "control_token" not in get()
    finally:
        stop()
    assert not (tmp_path / "runtime" / "daemons" / "composition-test").exists()
