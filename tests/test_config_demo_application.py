from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from dix.core import (
    ApplicationComponent,
    CompositionComponent,
    ModuleComponent,
    create_core_component_registry,
)
from dix.core.application import ApplicationInstanceSpec
from dix.modules import first_party_module_path

REPOSITORY = Path(__file__).resolve().parents[1]
EXAMPLE_MODULE = REPOSITORY / "examples" / "modules" / "acme" / "config_demo"


def _graph(tmp_path: Path):
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(first_party_module_path("dix/config"), module_id="dix/config")
    modules.load_module(EXAMPLE_MODULE, module_id="acme/config_demo")
    first = applications.create_instance(
        ApplicationInstanceSpec("config", "acme/config_demo/config", {}, tmp_path),
        owner_scope_id="first",
    )
    second = applications.create_instance(
        ApplicationInstanceSpec("config", "acme/config_demo/config", {}, tmp_path),
        owner_scope_id="second",
    )
    return registry, first, second


def test_application_owns_values_and_reports_pressure_result(tmp_path: Path) -> None:
    _, first, _ = _graph(tmp_path)
    result = first.api.require("pressure")()

    assert result["first"] == {
        "service": "alpha",
        "workers": 1,
        "enabled": True,
        "renderer": {"theme": "dark", "upper": False},
    }
    assert result["second"]["workers"] == 4
    assert result["second"]["enabled"] is False
    assert result["invalid"]["location"] == ["workers"]
    assert result["help"] == "Name of the configured service."


def test_two_application_instances_own_independent_model_types(tmp_path: Path) -> None:
    registry, first, second = _graph(tmp_path)
    applications = registry.require("application", ApplicationComponent)
    compositions = registry.require("composition", CompositionComponent)
    first_runtime = first.api.require("validate").__self__
    second_runtime = second.api.require("validate").__self__

    assert first_runtime.model is not second_runtime.model
    assert first.api.require("validate")(
        {"service": "one", "renderer": {"theme": "dark"}}
    )["service"] == "one"
    with pytest.raises(ValidationError):
        second.api.require("validate")(
            {"service": "two", "workers": "invalid", "renderer": {"theme": "light"}}
        )
    assert {(item.scope_id, item.id) for item in applications.instances()} == {
        ("first", "config"),
        ("second", "config"),
    }
    assert {(item.scope_id, item.id) for item in compositions.instances()} == {
        ("application:first:config", "config_model"),
        ("application:second:config", "config_model"),
    }


def test_visible_pressure_script_runs(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(REPOSITORY / "examples" / "run_config_demo.py")],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(REPOSITORY / "src")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["first"]["service"] == "alpha"
    assert result["second"]["service"] == "beta"
    assert result["invalid"]["location"] == ["workers"]
