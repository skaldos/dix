from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec
from dix.core.module.component import ModuleComponentError

REPOSITORY = Path(__file__).resolve().parents[1]
APP_MODULE = REPOSITORY / "unstable" / "modules" / "dix" / "core" / "app"
TARGET_MODULE = REPOSITORY / "examples" / "modules" / "acme" / "cli_demo"
CLI_MODULE = REPOSITORY / "unstable" / "modules" / "dix" / "core" / "cli"


def test_runner_is_a_regular_application_and_leaves_no_target_instance() -> None:
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(APP_MODULE, module_id="dix/core/app")
    modules.load_module(CLI_MODULE, module_id="dix/core/cli")
    modules.load_module(TARGET_MODULE, module_id="acme/cli_demo")
    runner = applications.create_instance(
        ApplicationInstanceSpec("runner", "dix/core/app/runner", {}, REPOSITORY),
        owner_scope_id="test",
    )

    descriptor = runner.api.describe_application("acme/cli_demo/tool")
    result = asyncio.run(
        runner.api.execute(
            "acme/cli_demo/tool",
            "render",
            kwargs={"value": "run", "count": 2, "upper": True},
        )
    )

    assert [item.id for item in descriptor.functions] == ["render"]
    assert result == "RUN\nRUN"
    assert [(item.scope_id, item.id) for item in applications.instances()] == [
        ("test", "runner")
    ]

    applications.destroy_instance("test", "runner")
    assert applications.instances() == ()


def test_runner_rejects_unloaded_targets_without_loading_modules(tmp_path: Path) -> None:
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(APP_MODULE, module_id="dix/core/app")
    runner = applications.create_instance(
        ApplicationInstanceSpec("runner", "dix/core/app/runner", {}, tmp_path),
        owner_scope_id="test",
    )
    before = modules.module_descriptors()

    with pytest.raises(Exception, match="not loaded"):
        asyncio.run(
            runner.api.execute(
                "unknown/tool",
                "run",
            )
        )

    assert modules.module_descriptors() == before


def test_runner_can_be_a_child_and_live_roots_block_module_unload(tmp_path: Path) -> None:
    parent_module = tmp_path / "parent"
    parent = parent_module / "apps" / "parent"
    parent.mkdir(parents=True)
    (parent / "app.toml").write_text(
        """[app]
id = "parent"

[apps.runner]
use = "dix/core/app/runner"
"""
    )
    (parent / "runtime.py").write_text(
        """class Runtime:
    def __init__(self, *, context, config, runner):
        self.runner = runner
"""
    )
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(APP_MODULE, module_id="dix/core/app")
    modules.load_module(parent_module, module_id="test/parent")
    root = applications.create_instance(
        ApplicationInstanceSpec("parent", "test/parent/parent", {}, tmp_path),
        owner_scope_id="test",
    )

    assert root.runtime.runner is applications.require_instance("test", "parent/runner").api
    with pytest.raises(ModuleComponentError, match="cannot be unloaded while it is in use"):
        modules.unload_module("dix/core/app")

    applications.destroy_instance("test", "parent")
    modules.unload_module("test/parent")
    modules.unload_module("dix/core/app")
    assert modules.module_descriptors() == ()
