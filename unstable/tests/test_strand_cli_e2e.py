from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec

REPOSITORY = Path(__file__).resolve().parents[1]
MODULES = REPOSITORY / "examples" / "modules"
UNSTABLE_MODULES = REPOSITORY / "unstable" / "modules"
KNOT_MODULE = UNSTABLE_MODULES / "dix" / "core" / "knot"
APP_MODULE = UNSTABLE_MODULES / "dix" / "core" / "app"
CLI_MODULE = UNSTABLE_MODULES / "dix" / "core" / "cli"
STRAND_CLI_MODULE = UNSTABLE_MODULES / "dix" / "core" / "strand_cli"
TARGET_MODULE = MODULES / "acme" / "cli_demo"
HARNESS = REPOSITORY / "unstable" / "tools" / "pressure" / "run_strand_cli.py"


def load_auto(monkeypatch):
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(KNOT_MODULE, module_id="dix/core/knot")
    modules.load_module(APP_MODULE, module_id="dix/core/app")
    modules.load_module(CLI_MODULE, module_id="dix/core/cli")
    modules.load_module(STRAND_CLI_MODULE, module_id="dix/core/strand_cli")
    target = modules.load_module(TARGET_MODULE, module_id="acme/cli_demo")
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
        ApplicationInstanceSpec(
            "auto",
            "dix/core/strand_cli/auto",
            {},
            REPOSITORY,
        ),
        owner_scope_id="test:strand-auto",
    )
    return modules, applications, auto, creations, calls


def test_strand_cli_describe_help_calls_failures_and_teardown(
    monkeypatch,
    capsys,
) -> None:
    modules, applications, auto, creations, calls = load_auto(monkeypatch)

    description = auto.api.require("describe")("acme/cli_demo/tool")
    assert json.loads(json.dumps(description)) == description
    command = description["commands"]["render"]
    assert command["strand"] == "acme/cli_demo/tool/render"
    assert command["input_model"]["fields"] == {
        "value": {"type": "string"},
        "count": {"type": "integer"},
        "upper": {"type": "boolean"},
    }
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
        ["render", "--value", "strand", "--count", "2", "--upper", "true"],
    ) == 0
    assert capsys.readouterr().out == "STRAND\nSTRAND\n"
    assert calls == [{"value": "strand", "count": 2, "upper": True}]
    assert len(creations) == 1

    assert auto.api.run(
        "acme/cli_demo/tool",
        {},
        ["render", "--value", "strand", "--count", "nope", "--upper", "true"],
    ) == 2
    assert "invalid value" in capsys.readouterr().err.lower()
    assert len(creations) == len(calls) == 1

    assert auto.api.run(
        "acme/cli_demo/tool",
        {},
        ["render", "--value", "strand", "--count", "1", "--upper", "maybe"],
    ) == 2
    assert "'true' or 'false'" in capsys.readouterr().err.lower()
    assert len(creations) == len(calls) == 1

    assert auto.api.run(
        "acme/cli_demo/tool",
        {},
        ["render", "--value", "strand", "--count", "1"],
    ) == 2
    assert "missing option '--upper'" in capsys.readouterr().err.lower()
    assert len(creations) == len(calls) == 1

    assert [(item.scope_id, item.id) for item in applications.instances()] == [
        ("test:strand-auto", "auto"),
        ("test:strand-auto", "auto/runner"),
    ]
    applications.destroy_instance("test:strand-auto", "auto")
    for module_id in (
        "acme/cli_demo",
        "dix/core/strand_cli",
        "dix/core/cli",
        "dix/core/app",
        "dix/core/knot",
    ):
        modules.unload_module(module_id)
    assert applications.instances() == ()


def test_visible_strand_cli_harness_executes_the_committed_stack() -> None:
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
