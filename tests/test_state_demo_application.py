from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from dix.core import (
    ApplicationComponent,
    CompositionComponent,
    ModuleComponent,
    create_core_component_registry,
)
from dix.core.application import ApplicationInstanceSpec
from dix.modules import first_party_module_path

REPOSITORY = Path(__file__).resolve().parents[1]
EXAMPLE_MODULE = REPOSITORY / "examples" / "modules" / "acme" / "state_demo"


def _graph(tmp_path: Path):
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(first_party_module_path("dix/state"), module_id="dix/state")
    modules.load_module(EXAMPLE_MODULE, module_id="acme/state_demo")
    first = applications.create_instance(
        ApplicationInstanceSpec("state", "acme/state_demo/state", {}, tmp_path),
        owner_scope_id="first",
    )
    second = applications.create_instance(
        ApplicationInstanceSpec("state", "acme/state_demo/state", {}, tmp_path),
        owner_scope_id="second",
    )
    return registry, first, second


def _initial_snapshot() -> dict[str, object]:
    return {
        "base": {"label": "base", "count": 1, "metadata": {"tags": ["base"]}},
        "reactive": {"mode": "idle", "enabled": True},
        "reactions": 0,
    }


def test_pressure_exercises_transparent_and_reactive_state_owners(tmp_path: Path) -> None:
    _, first, _ = _graph(tmp_path)
    result = first.api.require("pressure")()

    assert result["initial"] == _initial_snapshot()
    assert result["base_changed"] is True
    assert result["same_changed"] is False
    assert result["reactive_changed"] is True
    assert result["invalid"]["location"] == ["enabled"]
    assert result["detached_base"] == {
        "label": "updated",
        "count": 2,
        "metadata": {"tags": ["updated"]},
    }
    assert result["final"] == {
        "base": {
            "label": "updated",
            "count": 2,
            "metadata": {"tags": ["updated"]},
        },
        "reactive": {"mode": "active", "enabled": False},
        "reactions": 1,
    }


def test_application_roots_own_independent_state_graphs(tmp_path: Path) -> None:
    registry, first, second = _graph(tmp_path)
    applications = registry.require("application", ApplicationComponent)
    compositions = registry.require("composition", CompositionComponent)

    first.api.require("pressure")()
    assert second.api.require("snapshot")() == _initial_snapshot()
    assert {(item.scope_id, item.id) for item in applications.instances()} == {
        ("first", "state"),
        ("second", "state"),
    }

    first_scope = "application:first:state"
    second_scope = "application:second:state"
    first_instances = compositions.instances(scope_id=first_scope)
    second_instances = compositions.instances(scope_id=second_scope)
    assert {item.definition_id for item in first_instances} == {
        "acme/state_demo/combined",
        "acme/state_demo/base_config",
        "acme/state_demo/reactive_config",
        "dix/state/local",
        "dix/state/models",
    }
    assert {item.id for item in first_instances} == {item.id for item in second_instances}
    assert all(item.scope_id == first_scope for item in first_instances)
    assert all(item.scope_id == second_scope for item in second_instances)


def test_specs_make_exports_and_higher_wrapper_explicit(tmp_path: Path) -> None:
    registry, _, _ = _graph(tmp_path)
    compositions = registry.require("composition", CompositionComponent)

    base = compositions.describe_composition("acme/state_demo/base_config")
    reactive = compositions.describe_composition("acme/state_demo/reactive_config")
    combined = compositions.describe_composition("acme/state_demo/combined")

    assert {item.id: item.origin for item in base.functions} == {
        "get": "state.get",
        "set": "state.set",
    }
    assert {item.id: item.origin for item in reactive.functions} == {
        "get": "state.get",
        "reaction_count": None,
        "set": None,
    }
    assert {item.id: item.origin for item in combined.functions} == {
        "get_base": None,
        "get_reactive": None,
        "reaction_count": None,
        "set_base": None,
        "set_reactive": None,
    }

    graph = compositions.describe_dependency_graph("acme/state_demo/combined")
    direct = {(edge.alias, edge.target) for edge in graph.edges if edge.source == graph.root}
    assert direct == {
        ("base", "acme/state_demo/base_config"),
        ("reactive", "acme/state_demo/reactive_config"),
    }


def test_visible_pressure_script_runs(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(REPOSITORY / "examples" / "run_state_demo.py")],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(REPOSITORY / "src")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["initial"] == _initial_snapshot()
    assert result["final"]["reactions"] == 1
    assert result["invalid"]["location"] == ["enabled"]
