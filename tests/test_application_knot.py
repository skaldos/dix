from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from dix.core import (
    ApplicationComponent,
    ModuleComponent,
    StrandExecutionError,
    StrandInputError,
    create_core_component_registry,
    model_definition,
)
from dix.core.application import ApplicationInstanceSpec
from dix.core.module.component import ModuleComponentError

REPOSITORY = Path(__file__).resolve().parents[1]
MODULES = REPOSITORY / "examples" / "modules"
KNOT_MODULE = MODULES / "dix" / "core" / "knot"
TARGET_MODULE = MODULES / "acme" / "cli_demo"


def load_runner(
    tmp_path: Path,
    *,
    owner: str = "test",
    instance_id: str = "runner",
):
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(KNOT_MODULE, module_id="dix/core/knot")
    isolated_target = tmp_path / "target"
    shutil.copytree(TARGET_MODULE / "apps" / "tool", isolated_target / "apps" / "tool")
    target = modules.load_module(isolated_target, module_id="acme/cli_demo")
    runner = applications.create_instance(
        ApplicationInstanceSpec(
            instance_id,
            "dix/core/knot/runner",
            {},
            REPOSITORY,
        ),
        owner_scope_id=owner,
    )
    return modules, applications, runner, target


def test_application_function_is_bound_as_an_inspectable_model_strand(
    tmp_path: Path,
) -> None:
    modules, applications, runner, _ = load_runner(tmp_path)

    descriptors = runner.api.bind_application("acme/cli_demo/tool", {})

    assert [item.id for item in descriptors] == ["acme/cli_demo/tool/render"]
    descriptor = descriptors[0]
    assert descriptor.bound is True
    assert descriptor.handler_id == "application:acme/cli_demo/tool/render"
    assert descriptor.input_element.type == "model"
    assert descriptor.output_element.type == "string"
    model = model_definition(descriptor.input_element)
    assert tuple(model.schema) == ("value", "count", "upper")
    assert [item.type for item in model.schema.values()] == [
        "string",
        "integer",
        "boolean",
    ]
    assert applications.instances() == (runner,)

    applications.destroy_instance("test", "runner")
    modules.unload_module("acme/cli_demo")
    modules.unload_module("dix/core/knot")


def test_strand_call_executes_target_one_shot_and_validates_input(tmp_path: Path) -> None:
    modules, applications, runner, _ = load_runner(tmp_path)
    runner.api.bind_application("acme/cli_demo/tool", {})

    result = asyncio.run(
        runner.api.call(
            "acme/cli_demo/tool/render",
            {"value": "strand", "count": 2, "upper": True},
        )
    )

    assert result == "STRAND\nSTRAND"
    assert applications.instances() == (runner,)

    with pytest.raises(StrandInputError):
        asyncio.run(
            runner.api.call(
                "acme/cli_demo/tool/render",
                {"value": "strand", "count": "2", "upper": True},
            )
        )
    assert applications.instances() == (runner,)

    applications.destroy_instance("test", "runner")
    modules.unload_module("acme/cli_demo")
    modules.unload_module("dix/core/knot")


def test_target_failure_is_wrapped_and_target_graph_is_destroyed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules, applications, runner, target = load_runner(tmp_path)
    runtime_type = target.applications["acme/cli_demo/tool"].runtime_type

    def explode(self, *, value: str, count: int, upper: bool) -> str:
        raise RuntimeError(f"target exploded: {value}:{count}:{upper}")

    monkeypatch.setattr(runtime_type, "render", explode)
    runner.api.bind_application("acme/cli_demo/tool", {})

    with pytest.raises(StrandExecutionError) as error:
        asyncio.run(
            runner.api.call(
                "acme/cli_demo/tool/render",
                {"value": "broken", "count": 1, "upper": False},
            )
        )

    assert isinstance(error.value.__cause__, RuntimeError)
    assert applications.instances() == (runner,)

    applications.destroy_instance("test", "runner")
    modules.unload_module("acme/cli_demo")
    modules.unload_module("dix/core/knot")


def test_runner_instances_bind_the_same_strand_in_isolated_scopes(tmp_path: Path) -> None:
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(KNOT_MODULE, module_id="dix/core/knot")
    isolated_target = tmp_path / "target"
    shutil.copytree(TARGET_MODULE / "apps" / "tool", isolated_target / "apps" / "tool")
    modules.load_module(isolated_target, module_id="acme/cli_demo")
    first = applications.create_instance(
        ApplicationInstanceSpec("runner", "dix/core/knot/runner", {}, REPOSITORY),
        owner_scope_id="first",
    )
    second = applications.create_instance(
        ApplicationInstanceSpec("runner", "dix/core/knot/runner", {}, REPOSITORY),
        owner_scope_id="second",
    )

    first.api.bind_application("acme/cli_demo/tool", {"scope": "first"})
    second.api.bind_application("acme/cli_demo/tool", {"scope": "second"})
    assert first.api.describe_strand("acme/cli_demo/tool/render").handler_id == (
        second.api.describe_strand("acme/cli_demo/tool/render").handler_id
    )
    assert asyncio.run(
        first.api.call(
            "acme/cli_demo/tool/render",
            {"value": "first", "count": 1, "upper": False},
        )
    ) == "first"
    assert asyncio.run(
        second.api.call(
            "acme/cli_demo/tool/render",
            {"value": "second", "count": 1, "upper": True},
        )
    ) == "SECOND"

    applications.destroy_instance("first", "runner")
    applications.destroy_instance("second", "runner")
    modules.unload_module("acme/cli_demo")
    modules.unload_module("dix/core/knot")


def test_conflicting_rebind_fails_and_live_runner_blocks_unload(tmp_path: Path) -> None:
    modules, applications, runner, _ = load_runner(tmp_path)
    runner.api.bind_function(
        "test/render",
        "acme/cli_demo/tool",
        "render",
        {"profile": "first"},
    )
    assert runner.api.bind_function(
        "test/render",
        "acme/cli_demo/tool",
        "render",
        {"profile": "first"},
    ).id == "test/render"

    with pytest.raises(Exception, match="different application target"):
        runner.api.bind_function(
            "test/render",
            "acme/cli_demo/tool",
            "render",
            {"profile": "second"},
        )
    with pytest.raises(ModuleComponentError, match="cannot be unloaded while it is in use"):
        modules.unload_module("dix/core/knot")

    applications.destroy_instance("test", "runner")
    modules.unload_module("dix/core/knot")
    modules.unload_module("acme/cli_demo")
