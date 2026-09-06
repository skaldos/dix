from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec

REPOSITORY = Path(__file__).resolve().parents[1]
MODULES = REPOSITORY / "examples" / "modules"
APP_MODULE = MODULES / "dix" / "core" / "app"
CLI_MODULE = MODULES / "dix" / "core" / "cli"
DEMO_MODULE = MODULES / "acme" / "cli_demo"
HARNESS = REPOSITORY / "examples" / "run_auto_cli.py"


def load_auto(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target_module = tmp_path / "target-module"
    shutil.copytree(DEMO_MODULE / "apps" / "tool", target_module / "apps" / "tool")

    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(APP_MODULE, module_id="dix/core/app")
    modules.load_module(CLI_MODULE, module_id="dix/core/cli")
    target = modules.load_module(target_module, module_id="acme/cli_demo")
    assert applications.instances() == ()

    runtime_type = target.applications["acme/cli_demo/tool"].runtime_type
    creations: list[object] = []
    calls: list[dict[str, object]] = []
    original_init = runtime_type.__init__
    original_render = runtime_type.render

    def tracked_init(self, *, context, config):
        creations.append(context)
        original_init(self, context=context, config=config)

    def tracked_render(self, *, value: str, count: int, upper: bool) -> str:
        calls.append({"value": value, "count": count, "upper": upper})
        return original_render(self, value=value, count=count, upper=upper)

    monkeypatch.setattr(runtime_type, "__init__", tracked_init)
    monkeypatch.setattr(runtime_type, "render", tracked_render)
    auto = applications.create_instance(
        ApplicationInstanceSpec("auto", "dix/core/cli/auto", {}, tmp_path),
        owner_scope_id="test:auto",
    )
    return modules, applications, auto, runtime_type, creations, calls


def assert_only_auto_graph(applications: ApplicationComponent) -> None:
    assert {(item.scope_id, item.id) for item in applications.instances()} == {
        ("test:auto", "auto"),
        ("test:auto", "auto/runner"),
    }


def test_auto_cli_real_graph_contract_help_calls_failures_and_teardown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    modules, applications, auto, runtime_type, creations, calls = load_auto(
        tmp_path, monkeypatch
    )
    assert_only_auto_graph(applications)
    assert creations == calls == []

    original_read_text = Path.read_text

    def guarded_read_text(path: Path, *args, **kwargs):
        if path.name in {"cli.toml", "render_input.toml"}:
            raise AssertionError(f"automatic CLI read forbidden B-006 file: {path}")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    description = auto.api.require("describe")("acme/cli_demo/tool")
    assert json.loads(json.dumps(description)) == description
    assert [item["name"] for item in description["commands"]["render"]["parameters"]] == [
        "value",
        "count",
        "upper",
    ]
    assert creations == calls == []

    assert auto.api.run("acme/cli_demo/tool", {}, ["render", "--help"]) == 0
    help_output = capsys.readouterr()
    assert "--value" in help_output.out
    assert "--count" in help_output.out
    assert "--upper" in help_output.out
    assert creations == calls == []

    assert auto.api.run(
        "acme/cli_demo/tool",
        {},
        ["render", "--value", "test", "--count", "5", "--upper", "true"],
    ) == 0
    assert capsys.readouterr().out == "TEST\nTEST\nTEST\nTEST\nTEST\n"
    assert calls[-1] == {"value": "test", "count": 5, "upper": True}
    assert len(creations) == 1
    assert_only_auto_graph(applications)

    assert auto.api.run(
        "acme/cli_demo/tool",
        {},
        ["render", "--value", "test", "--count", "2", "--upper", "false"],
    ) == 0
    assert capsys.readouterr().out == "test\ntest\n"
    assert calls[-1] == {"value": "test", "count": 2, "upper": False}
    assert len(creations) == 2
    assert_only_auto_graph(applications)

    assert auto.api.run(
        "acme/cli_demo/tool",
        {},
        ["render", "--value", "test", "--count", "nope", "--upper", "true"],
    ) == 2
    assert "invalid value" in capsys.readouterr().err.lower()
    assert len(creations) == 2
    assert len(calls) == 2

    assert auto.api.run(
        "acme/cli_demo/tool",
        {},
        ["render", "--value", "test", "--count", "1"],
    ) == 2
    assert "missing option '--upper'" in capsys.readouterr().err.lower()
    assert len(creations) == 2
    assert len(calls) == 2

    def failing_render(self, *, value: str, count: int, upper: bool) -> str:
        calls.append({"value": value, "count": count, "upper": upper})
        raise RuntimeError("target exploded")

    monkeypatch.setattr(runtime_type, "render", failing_render)
    assert auto.api.run(
        "acme/cli_demo/tool",
        {},
        ["render", "--value", "test", "--count", "1", "--upper", "true"],
    ) == 1
    assert "target exploded" in capsys.readouterr().err
    assert len(creations) == 3
    assert len(calls) == 3
    assert_only_auto_graph(applications)

    applications.destroy_instance("test:auto", "auto")
    assert applications.instances() == ()
    modules.unload_module("acme/cli_demo")
    modules.unload_module("dix/core/cli")
    modules.unload_module("dix/core/app")
    assert modules.module_descriptors() == ()


def test_visible_auto_cli_harness_executes_the_committed_stack() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(HARNESS),
            "acme/cli_demo/tool",
            "render",
            "--value",
            "test",
            "--count",
            "2",
            "--upper",
            "true",
        ],
        cwd=REPOSITORY,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "TEST\nTEST\n"
    assert result.stderr == ""
