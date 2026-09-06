from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from dix.core import (
    CompositionComponent,
    ModuleComponent,
    create_core_component_registry,
    derive_function_contract,
)
from dix.core.application import ApplicationFunctionDescriptor
from dix.core.composition import CompositionInstanceSpec

REPOSITORY = Path(__file__).resolve().parents[1]
CLI_MODULE = REPOSITORY / "examples" / "modules" / "dix" / "core" / "cli"
APP_MODULE = REPOSITORY / "examples" / "modules" / "dix" / "core" / "app"


def write_contract(root: Path, *, cli_extra: str = "", model_extra: str = "") -> Path:
    (root / "models").mkdir(parents=True, exist_ok=True)
    (root / "models" / "render_input.toml").write_text(
        """[model]
name = "render_input"
version = "1"

[fields.value]
type = "string"

[fields.count]
type = "integer"

[fields.upper]
type = "boolean"
"""
        + model_extra
    )
    spec = root / "cli.toml"
    spec.write_text(
        """[cli]
name = "test-cli"
description = "Declarative test CLI."
no_args = "help"

[groups.text]
description = "Text operations."

[commands.render]
path = ["text", "render"]
target = "tool.render"
model = "models/render_input.toml"
description = "Render text."

[commands.render.options.value]
description = "Text value."
env = ["DIX_TEST_VALUE"]

[commands.render.options.count]
names = ["--count", "-c"]
description = "Repeat count."
env = ["DIX_TEST_COUNT"]

[commands.render.options.upper]
description = "Uppercase output."
env = ["DIX_TEST_UPPER"]
"""
        + cli_extra
    )
    return spec


def cli_runtime(tmp_path: Path, instance_id: str = "cli"):
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    compositions = registry.require("composition", CompositionComponent)
    modules.load_module(APP_MODULE, module_id="dix/core/app")
    modules.load_module(CLI_MODULE, module_id="dix/core/cli")
    instance = compositions.create_instance(
        CompositionInstanceSpec(instance_id, "dix/core/cli/typer_cli", {}, tmp_path),
        owner_scope_id="test",
    )
    return modules, compositions, instance


def target_mapping(function):
    signature = inspect.signature(function)
    descriptor = ApplicationFunctionDescriptor(
        id="render",
        application_id="test/tool",
        source="local",
        origin=None,
        signature=signature,
        return_annotation=signature.return_annotation,
        docstring=inspect.getdoc(function),
        contract=derive_function_contract("test/tool", "render", signature),
    )
    return {"tool.render": {"function": function, "descriptor": descriptor}}


def test_describe_is_normalized_json_serializable_and_models_are_cached(
    tmp_path: Path,
) -> None:
    spec = write_contract(tmp_path)
    _, _, instance = cli_runtime(tmp_path)

    def render(*, value: str, count: int, upper: bool) -> str:
        return value

    targets = target_mapping(render)
    first = instance.api.require("describe")(spec_path=spec, targets=targets)
    second = instance.api.require("describe")(spec_path=spec, targets=targets)
    application = instance.api.build(spec_path=spec, targets=targets)

    assert first == second
    assert json.loads(json.dumps(first)) == first
    assert first["cli"] == {
        "name": "test-cli",
        "description": "Declarative test CLI.",
        "no_args": "help",
    }
    assert first["commands"]["render"]["path"] == ["text", "render"]
    assert first["commands"]["render"]["options"]["value"] == {
        "type": "string",
        "names": ["--value"],
        "description": "Text value.",
        "env": ["DIX_TEST_VALUE"],
        "show_env": True,
    }
    assert instance.runtime.datamodel.registration_count == 1
    assert application.info.name == "test-cli"


def test_invoke_help_env_precedence_named_options_and_exit_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = write_contract(tmp_path)
    _, _, instance = cli_runtime(tmp_path)
    calls: list[dict[str, object]] = []

    def render(*, value: str, count: int, upper: bool) -> str:
        calls.append({"value": value, "count": count, "upper": upper})
        rendered = value.upper() if upper else value
        return "\n".join(rendered for _ in range(count))

    targets = target_mapping(render)
    assert instance.api.invoke(spec_path=spec, targets=targets, argv=[]) == 0
    root_help = capsys.readouterr()
    assert "Declarative test CLI." in root_help.out
    assert root_help.err == ""
    assert calls == []

    assert instance.api.invoke(
        spec_path=spec, targets=targets, argv=["text", "render", "--help"]
    ) == 0
    command_help = capsys.readouterr()
    assert "DIX_TEST_VALUE" in command_help.out
    assert "DIX_TEST_COUNT" in command_help.out
    assert "DIX_TEST_UPPER" in command_help.out
    assert "TRUE|FALSE" in command_help.out
    assert calls == []

    assert instance.api.invoke(
        spec_path=spec,
        targets=targets,
        argv=["text", "render", "--value", "hello", "--count", "2"],
    ) == 2
    missing_boolean = capsys.readouterr()
    assert missing_boolean.out == ""
    assert "missing option '--upper'" in missing_boolean.err.lower()
    assert "DIX_TEST_UPPER" in missing_boolean.err
    assert "['DIX_TEST_UPPER']" not in missing_boolean.err
    assert calls == []

    assert instance.api.invoke(
        spec_path=spec,
        targets=targets,
        argv=["text", "render", "--value", "hello", "--count", "2", "--upper", "true"],
    ) == 0
    direct = capsys.readouterr()
    assert direct.out == "HELLO\nHELLO\n"
    assert direct.err == ""
    assert calls[-1] == {"value": "hello", "count": 2, "upper": True}

    assert instance.api.invoke(
        spec_path=spec,
        targets=targets,
        argv=["text", "render", "--value", "plain", "--count", "1", "--upper", "false"],
    ) == 0
    explicit_false = capsys.readouterr()
    assert explicit_false.out == "plain\n"
    assert explicit_false.err == ""
    assert calls[-1] == {"value": "plain", "count": 1, "upper": False}

    monkeypatch.setenv("DIX_TEST_VALUE", "environment")
    monkeypatch.setenv("DIX_TEST_COUNT", "1")
    monkeypatch.setenv("DIX_TEST_UPPER", "false")
    assert instance.api.invoke(
        spec_path=spec,
        targets=targets,
        argv=["text", "render", "--value", "direct"],
    ) == 0
    precedence = capsys.readouterr()
    assert precedence.out == "direct\n"
    assert calls[-1] == {"value": "direct", "count": 1, "upper": False}

    call_count = len(calls)
    assert instance.api.invoke(
        spec_path=spec,
        targets=targets,
        argv=[
            "text",
            "render",
            "positional",
            "--value",
            "hello",
            "--count",
            "1",
            "--upper",
            "true",
        ],
    ) == 2
    positional = capsys.readouterr()
    assert positional.out == ""
    assert "unexpected extra argument" in positional.err.lower()
    assert len(calls) == call_count

    assert instance.api.invoke(
        spec_path=spec,
        targets=targets,
        argv=[
            "text",
            "render",
            "--value",
            "hello",
            "--count",
            "nope",
            "--upper",
            "true",
        ],
    ) == 2
    invalid = capsys.readouterr()
    assert invalid.out == ""
    assert "not a valid int" in invalid.err.lower()
    assert len(calls) == call_count

    assert instance.api.invoke(
        spec_path=spec,
        targets=targets,
        argv=[
            "text",
            "render",
            "--value",
            "hello",
            "--count",
            "1",
            "--upper",
            "sometimes",
        ],
    ) == 2
    invalid_boolean = capsys.readouterr()
    assert invalid_boolean.out == ""
    assert "invalid value for '--upper'" in invalid_boolean.err.lower()
    assert len(calls) == call_count


def test_none_target_and_target_failure_have_stable_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = write_contract(tmp_path)
    _, _, instance = cli_runtime(tmp_path)

    def no_output(*, value: str, count: int, upper: bool) -> None:
        return None

    assert instance.api.invoke(
        spec_path=spec,
        targets=target_mapping(no_output),
        argv=["text", "render", "--value", "value", "--count", "1", "--upper", "true"],
    ) == 0
    assert capsys.readouterr() == ("", "")

    def failure(*, value: str, count: int, upper: bool) -> str:
        raise RuntimeError("target boom")

    assert instance.api.invoke(
        spec_path=spec,
        targets=target_mapping(failure),
        argv=["text", "render", "--value", "value", "--count", "1", "--upper", "true"],
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: target boom\n"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("\nunknown = true\n", "extra_forbidden"),
        ("\n[commands.render.options.extra]\n", "option/model mismatch"),
    ],
)
def test_cli_contract_is_strict_and_fails_before_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mutation: str,
    message: str,
) -> None:
    spec = write_contract(tmp_path, cli_extra=mutation)
    _, _, instance = cli_runtime(tmp_path)
    calls: list[object] = []

    def render(*, value: str, count: int, upper: bool) -> str:
        calls.append(value)
        return value

    assert instance.api.invoke(spec_path=spec, targets=target_mapping(render), argv=[]) == 2
    assert message in capsys.readouterr().err
    assert calls == []


def test_model_contract_target_allowlist_and_signatures_are_strict(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = write_contract(tmp_path, model_extra="\nunknown = true\n")
    _, _, instance = cli_runtime(tmp_path)

    def render(*, value: str, count: int, upper: bool) -> str:
        return value

    assert instance.api.invoke(spec_path=spec, targets=target_mapping(render), argv=[]) == 2
    assert "extra_forbidden" in capsys.readouterr().err

    write_contract(tmp_path)
    assert instance.api.invoke(spec_path=spec, targets={}, argv=[]) == 2
    assert "unavailable target 'tool.render'" in capsys.readouterr().err

    def variadic(*values: object, **named: object) -> str:
        return "unreachable"

    assert instance.api.invoke(spec_path=spec, targets=target_mapping(variadic), argv=[]) == 2
    assert "unsupported parameters" in capsys.readouterr().err

    def mismatched(*, value: str, count: int) -> str:
        return value

    assert instance.api.invoke(spec_path=spec, targets=target_mapping(mismatched), argv=[]) == 2
    assert "model/target mismatch" in capsys.readouterr().err


def test_two_composition_instances_share_neither_models_nor_command_trees(
    tmp_path: Path,
) -> None:
    spec = write_contract(tmp_path)
    _, compositions, first = cli_runtime(tmp_path, "first")
    second = compositions.create_instance(
        CompositionInstanceSpec("second", "dix/core/cli/typer_cli", {}, tmp_path),
        owner_scope_id="test",
    )

    def render(*, value: str, count: int, upper: bool) -> str:
        return value

    targets = target_mapping(render)
    first_app = first.api.build(spec_path=spec, targets=targets)
    second_app = second.api.build(spec_path=spec, targets=targets)

    assert first_app is not second_app
    assert first.runtime.datamodel is not second.runtime.datamodel
    assert first.runtime.datamodel.registration_count == 1
    assert second.runtime.datamodel.registration_count == 1
