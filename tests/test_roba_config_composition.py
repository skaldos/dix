from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import ValidationError

from dix.core import CompositionComponent, ModuleComponent, create_core_component_registry
from dix.core.composition import CompositionInstanceSpec
from dix.modules import first_party_module_path


EXPECTED_DEFAULTS = {
    "daemon_id": "default",
    "runtime_root": "~/.roba/runtime",
    "logs_root": "~/.roba/logs",
    "timeout": 5.0,
}


def _components() -> CompositionComponent:
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    compositions = registry.require("composition", CompositionComponent)
    modules.load_module(first_party_module_path("dix/state"), module_id="dix/state")
    modules.load_module(first_party_module_path("dix/cli"), module_id="dix/cli")
    modules.load_module(first_party_module_path("dix/roba"), module_id="dix/roba")
    return compositions


def _instance(tmp_path: Path):
    return _components().create_instance(
        CompositionInstanceSpec("config", "dix/roba/config", {}, tmp_path),
        owner_scope_id="test",
    )


def test_defaults_and_full_model_set_are_owned_by_one_config_instance(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    get = instance.api.require("get")
    set_value = instance.api.require("set")
    assert {item.id for item in instance.api.functions()} == {"get", "set", "environment"}
    assert get() == EXPECTED_DEFAULTS
    changed = {**EXPECTED_DEFAULTS, "daemon_id": "other", "timeout": "2.5"}
    assert set_value(changed) is True
    assert get() == {**EXPECTED_DEFAULTS, "daemon_id": "other", "timeout": 2.5}
    before = get()
    with pytest.raises(ValidationError):
        set_value({**EXPECTED_DEFAULTS, "timeout": "broken"})
    assert get() == before


def test_environment_removes_inherited_roba_values_and_sets_only_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KEEP_ME", "yes")
    monkeypatch.setenv("ROBA_RUNTIME_ROOT", "/inherited/runtime")
    monkeypatch.setenv("ROBA_LOGS_ROOT", "/inherited/logs")
    monkeypatch.setenv("ROBA_CTL_BIN", "/inherited/ctl")
    monkeypatch.setenv("ROBA_OTHER", "forbidden")
    instance = _instance(tmp_path)
    environment = instance.api.require("environment")()
    assert environment["KEEP_ME"] == "yes"
    assert environment["ROBA_RUNTIME_ROOT"] == "~/.roba/runtime"
    assert environment["ROBA_LOGS_ROOT"] == "~/.roba/logs"
    assert set(key for key in environment if key.startswith("ROBA_")) == {
        "ROBA_RUNTIME_ROOT",
        "ROBA_LOGS_ROOT",
    }
