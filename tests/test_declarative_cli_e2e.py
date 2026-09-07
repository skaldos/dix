from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dix.cli import main as management_main
from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec

REPOSITORY = Path(__file__).resolve().parents[1]
MODULES = REPOSITORY / "examples" / "modules"
UNSTABLE_MODULES = REPOSITORY / "unstable" / "modules"
CLI_MODULE = UNSTABLE_MODULES / "dix" / "core" / "cli"
APP_MODULE = UNSTABLE_MODULES / "dix" / "core" / "app"
DEMO_MODULE = MODULES / "acme" / "cli_demo"
HARNESS = REPOSITORY / "unstable" / "tools" / "pressure" / "run_cli_demo.py"


def load_demo(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, object]] = []
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(APP_MODULE, module_id="dix/core/app")
    modules.load_module(CLI_MODULE, module_id="dix/core/cli")
    loaded = modules.load_module(DEMO_MODULE, module_id="acme/cli_demo")
    tool_type = loaded.applications["acme/cli_demo/tool"].runtime_type
    original = tool_type.render

    def tracked(self, *, value: str, count: int, upper: bool) -> str:
        calls.append({"value": value, "count": count, "upper": upper})
        return original(self, value=value, count=count, upper=upper)

    monkeypatch.setattr(tool_type, "render", tracked)
    instance = applications.create_instance(
        ApplicationInstanceSpec("cli", "acme/cli_demo/cli", {}, REPOSITORY),
        owner_scope_id="e2e",
    )
    return calls, modules, applications, instance


def test_real_module_load_create_describe_and_allowlist_are_side_effect_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, modules, applications, instance = load_demo(monkeypatch)

    assert calls == []
    description = instance.api.require("describe")()
    assert calls == []
    assert json.loads(json.dumps(description)) == description
    assert description["commands"]["render"]["target"] == "tool.render"
    assert {item.id for item in instance.api.functions()} == {"describe", "run"}

    tool = applications.require_instance("e2e", "cli/tool")
    assert {item.id for item in tool.api.functions()} == {"render"}
    applications.destroy_instance("e2e", "cli")
    modules.unload_module("acme/cli_demo")
    modules.unload_module("dix/core/cli")
    modules.unload_module("dix/core/app")
    assert calls == []


def test_real_cli_help_named_calls_env_precedence_and_datamodel(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls, _, _, instance = load_demo(monkeypatch)
    run = instance.api.require("run")

    assert run([]) == 0
    root_help = capsys.readouterr()
    assert "Declarative CLI application pressure test." in root_help.out
    assert "text" in root_help.out
    assert root_help.err == ""

    assert run(["text", "render", "--help"]) == 0
    command_help = capsys.readouterr()
    assert "Render one value repeatedly." in command_help.out
    assert "DIX_CLI_DEMO_VALUE" in command_help.out
    assert "DIX_CLI_DEMO_COUNT" in command_help.out
    assert "DIX_CLI_DEMO_UPPER" in command_help.out
    assert "TRUE|FALSE" in command_help.out

    assert run(["text", "render", "--value", "hello", "--count", "2"]) == 2
    missing_boolean = capsys.readouterr()
    assert missing_boolean.out == ""
    assert "missing option '--upper'" in missing_boolean.err.lower()
    assert "DIX_CLI_DEMO_UPPER" in missing_boolean.err
    assert "['DIX_CLI_DEMO_UPPER']" not in missing_boolean.err
    assert calls == []

    assert (
        run(["text", "render", "--value", "hello", "--count", "2", "--upper", "true"])
        == 0
    )
    direct = capsys.readouterr()
    assert direct.out == "HELLO\nHELLO\n"
    assert direct.err == ""
    assert calls[-1] == {"value": "hello", "count": 2, "upper": True}

    assert (
        run(["text", "render", "--value", "plain", "--count", "1", "--upper", "false"])
        == 0
    )
    explicit_false = capsys.readouterr()
    assert explicit_false.out == "plain\n"
    assert explicit_false.err == ""
    assert calls[-1] == {"value": "plain", "count": 1, "upper": False}

    monkeypatch.setenv("DIX_CLI_DEMO_VALUE", "hello")
    monkeypatch.setenv("DIX_CLI_DEMO_COUNT", "2")
    assert run(["text", "render", "--upper", "true"]) == 0
    environment = capsys.readouterr()
    assert environment.out == "HELLO\nHELLO\n"
    assert calls[-1] == {"value": "hello", "count": 2, "upper": True}

    monkeypatch.setenv("DIX_CLI_DEMO_VALUE", "wrong")
    monkeypatch.setenv("DIX_CLI_DEMO_COUNT", "1")
    monkeypatch.setenv("DIX_CLI_DEMO_UPPER", "false")
    assert run(["text", "render", "--value", "right"]) == 0
    precedence = capsys.readouterr()
    assert precedence.out == "right\n"
    assert calls[-1] == {"value": "right", "count": 1, "upper": False}


def test_invalid_values_and_unmapped_commands_never_call_target(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls, _, _, instance = load_demo(monkeypatch)
    run = instance.api.require("run")
    monkeypatch.delenv("DIX_CLI_DEMO_VALUE", raising=False)
    monkeypatch.delenv("DIX_CLI_DEMO_COUNT", raising=False)
    monkeypatch.delenv("DIX_CLI_DEMO_UPPER", raising=False)

    assert (
        run(
            [
                "text",
                "render",
                "hello",
                "--value",
                "value",
                "--count",
                "1",
                "--upper",
                "true",
            ]
        )
        == 2
    )
    positional = capsys.readouterr()
    assert positional.out == ""
    assert "error" in positional.err.lower()
    assert calls == []

    assert (
        run(
            [
                "text",
                "render",
                "--value",
                "hello",
                "--count",
                "nope",
                "--upper",
                "true",
            ]
        )
        == 2
    )
    invalid = capsys.readouterr()
    assert invalid.out == ""
    assert "not a valid int" in invalid.err.lower()
    assert calls == []

    assert (
        run(
            [
                "text",
                "render",
                "--value",
                "hello",
                "--count",
                "1",
                "--upper",
                "sometimes",
            ]
        )
        == 2
    )
    invalid_boolean = capsys.readouterr()
    assert invalid_boolean.out == ""
    assert "invalid value for '--upper'" in invalid_boolean.err.lower()
    assert calls == []

    assert run(["text", "hidden"]) == 2
    hidden = capsys.readouterr()
    assert hidden.out == ""
    assert "no such command" in hidden.err.lower()
    assert calls == []


def test_two_cli_application_roots_have_private_model_and_command_scopes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, _, applications, first = load_demo(monkeypatch)
    second = applications.create_instance(
        ApplicationInstanceSpec("second", "acme/cli_demo/cli", {}, REPOSITORY),
        owner_scope_id="e2e",
    )
    first_cli = first.compositions["cli"]
    second_cli = second.compositions["cli"]

    assert first.api.require("run")(["--help"]) == 0
    assert second.api.require("run")(["--help"]) == 0
    capsys.readouterr()

    assert first_cli is not second_cli
    assert first_cli.runtime.datamodel is not second_cli.runtime.datamodel
    assert first_cli.runtime.datamodel.registration_count == 1
    assert second_cli.runtime.datamodel.registration_count == 1


def test_harness_uses_explicit_teardown_and_changes_no_sources() -> None:
    before = source_digest()
    result = subprocess.run(
        [
            sys.executable,
            str(HARNESS),
            "text",
            "render",
            "--value",
            "hello",
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
    assert result.stdout == "HELLO\nHELLO\n"
    assert result.stderr == ""
    assert source_digest() == before


def test_existing_management_cli_remains_available(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(REPOSITORY)

    assert management_main(["app", "list", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "acme/cli_demo/cli" in {item["id"] for item in payload}


def source_digest() -> str:
    digest = hashlib.sha256()
    roots = (CLI_MODULE, DEMO_MODULE, HARNESS)
    paths = [HARNESS]
    for root in roots[:2]:
        paths.extend(
            path
            for path in root.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )
    for path in sorted(paths):
        digest.update(str(path.relative_to(REPOSITORY)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()
