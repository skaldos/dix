from __future__ import annotations

from pathlib import Path

import pytest

from dix.core import (
    ApplicationComponent,
    CompositionComponent,
    ModuleComponent,
    create_core_component_registry,
)
from dix.core.application import ApplicationInstanceSpec
from dix.core.composition import CompositionInstanceSpec
from dix.modules import first_party_module_path


def _write_target(module: Path, *, spec: str, runtime: str) -> None:
    root = module / "apps" / "target"
    root.mkdir(parents=True)
    (root / "app.toml").write_text(spec)
    (root / "runtime.py").write_text(runtime)


def _runtime(tmp_path: Path, *, spec: str, runtime: str):
    target_module = tmp_path / "target"
    _write_target(target_module, spec=spec, runtime=runtime)
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    compositions = registry.require("composition", CompositionComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(first_party_module_path("dix/cli"), module_id="dix/cli")
    modules.load_module(target_module, module_id="acme/target")
    cli = compositions.create_instance(
        CompositionInstanceSpec("cli", "dix/cli/typer", {}, tmp_path),
        owner_scope_id="test",
    )
    target = applications.create_instance(
        ApplicationInstanceSpec("target", "acme/target/target", {}, tmp_path),
        owner_scope_id="test",
    )
    return cli.api.require("invoke"), target.api


def test_groups_exact_names_help_docstrings_options_env_and_calls(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoke, target = _runtime(
        tmp_path,
        spec="""\
[app]
id = "target"
[functions.echo_value]
[functions.quiet]
[functions.number]
[functions.delayed]
[functions.explode]
""",
        runtime="""\
from __future__ import annotations
import asyncio

class Runtime:
    calls = []

    def __init__(self, *, context, config): pass

    def echo_value(self, *, value: str, count: int = 1, upper: bool = False) -> str:
        \"\"\"Render one value repeatedly.\"\"\"
        self.calls.append((\"echo_value\", value, count, upper))
        rendered = value.upper() if upper else value
        return \"\\n\".join(rendered for _ in range(count))

    def quiet(self, *, value: str) -> None:
        \"\"\"Return no output.\"\"\"
        self.calls.append((\"quiet\", value))

    def number(self) -> int:
        \"\"\"Return integer data.\"\"\"
        self.calls.append((\"number\",))
        return 7

    async def delayed(self, *, value: str) -> str:
        \"\"\"Return through an awaitable.\"\"\"
        await asyncio.sleep(0)
        self.calls.append((\"delayed\", value))
        return f\"async:{value}\"

    def explode(self) -> None:
        \"\"\"Raise one target error.\"\"\"
        self.calls.append((\"explode\",))
        raise RuntimeError(\"target exploded\")

    def private_helper(self):
        raise AssertionError(\"must remain private\")
""",
    )

    assert invoke(name="my_cli", targets={"test_group": target}, argv=["--help"]) == 0
    root_help = capsys.readouterr()
    assert "test_group" in root_help.out
    assert "echo_value" not in root_help.out
    assert "private_helper" not in root_help.out
    assert target.require("echo_value").__self__.calls == []

    assert invoke(
        name="my_cli",
        targets={"test_group": target},
        argv=["test_group", "echo_value", "--help"],
    ) == 0
    command_help = capsys.readouterr()
    assert "Render one value repeatedly." in command_help.out
    assert "--value" in command_help.out
    assert "--count" in command_help.out
    assert "--upper" in command_help.out
    assert "MY_CLI_TEST_GROUP_ECHO_VALUE_VALUE" in command_help.out
    assert target.require("echo_value").__self__.calls == []

    assert invoke(
        name="my_cli",
        targets={"test_group": target},
        argv=[
            "test_group",
            "echo_value",
            "--value",
            "test",
            "--count",
            "2",
            "--upper",
            "true",
        ],
    ) == 0
    assert capsys.readouterr().out == "TEST\nTEST\n"

    assert invoke(
        name="my_cli",
        targets={"test_group": target},
        argv=[
            "test_group",
            "echo_value",
            "--value",
            "test",
            "--upper",
            "false",
        ],
    ) == 0
    assert capsys.readouterr().out == "test\n"

    monkeypatch.setenv("MY_CLI_TEST_GROUP_ECHO_VALUE_VALUE", "environment")
    assert invoke(
        name="my_cli",
        targets={"test_group": target},
        argv=["test_group", "echo_value", "--upper", "false"],
    ) == 0
    assert capsys.readouterr().out == "environment\n"

    assert invoke(
        name="my_cli",
        targets={"test_group": target},
        argv=["test_group", "delayed", "--value", "ready"],
    ) == 0
    assert capsys.readouterr().out == "async:ready\n"

    assert invoke(
        name="my_cli",
        targets={"test_group": target},
        argv=["test_group", "quiet", "--value", "ignored"],
    ) == 0
    assert capsys.readouterr().out == ""

    assert invoke(
        name="my_cli",
        targets={"test_group": target},
        argv=["test_group", "number"],
    ) == 0
    assert capsys.readouterr().out == "7\n"

    assert invoke(
        name="my_cli",
        targets={"test_group": target},
        argv=["test_group", "explode"],
    ) == 1
    error = capsys.readouterr()
    assert "target exploded" in error.err


def test_same_function_name_is_isolated_by_group(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke, target = _runtime(
        tmp_path,
        spec='[app]\nid = "target"\n[functions.status]\n',
        runtime="""\
class Runtime:
    def __init__(self, *, context, config):
        self.context = context
    def status(self) -> str:
        return self.context.instance_id
""",
    )
    assert (
        invoke(
            name="my_cli",
            targets={"first": target, "second": target},
            argv=["first", "status"],
        )
        == 0
    )
    assert capsys.readouterr().out == "target\n"
    assert (
        invoke(
            name="my_cli",
            targets={"first": target, "second": target},
            argv=["second", "status"],
        )
        == 0
    )
    assert capsys.readouterr().out == "target\n"


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ("value", "has no annotation"),
        ("value: str, /", "unsupported positional-only"),
        ("*values: str", "unsupported variadic"),
        ("**values: str", "unsupported variadic"),
    ],
)
def test_unsupported_signatures_fail_before_target_call(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    parameters: str,
    message: str,
) -> None:
    invoke, target = _runtime(
        tmp_path,
        spec='[app]\nid = "target"\n[functions.invalid]\n',
        runtime=f"""\
class Runtime:
    calls = 0
    def __init__(self, *, context, config): pass
    def invalid(self, {parameters}):
        self.calls += 1
""",
    )
    assert invoke(name="my_cli", targets={"test": target}, argv=["--help"]) == 2
    assert message in capsys.readouterr().err
    assert target.require("invalid").__self__.calls == 0


def test_typer_conversion_failure_does_not_call_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke, target = _runtime(
        tmp_path,
        spec='[app]\nid = "target"\n[functions.number]\n',
        runtime="""\
class Runtime:
    calls = 0
    def __init__(self, *, context, config): pass
    def number(self, *, value: int) -> str:
        self.calls += 1
        return str(value)
""",
    )
    assert invoke(
        name="my_cli",
        targets={"test": target},
        argv=["test", "number", "--value", "not-an-int"],
    ) == 2
    assert "invalid" in capsys.readouterr().err.lower()
    assert target.require("number").__self__.calls == 0


def test_environment_name_collision_is_rejected_before_target_call(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke, target = _runtime(
        tmp_path,
        spec='[app]\nid = "target"\n[functions.read_value]\n',
        runtime="""\
class Runtime:
    calls = 0
    def __init__(self, *, context, config): pass
    def read_value(self, *, item: str) -> str:
        self.calls += 1
        return item
""",
    )
    assert invoke(
        name="my_cli",
        targets={"same-name": target, "same_name": target},
        argv=["--help"],
    ) == 2
    assert "environment name collision" in capsys.readouterr().err
    assert target.require("read_value").__self__.calls == 0


def test_annotation_not_supported_by_typer_fails_before_target_call(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invoke, target = _runtime(
        tmp_path,
        spec='[app]\nid = "target"\n[functions.unsupported]\n',
        runtime="""\
class Runtime:
    calls = 0
    def __init__(self, *, context, config): pass
    def unsupported(self, *, value: complex) -> str:
        self.calls += 1
        return str(value)
""",
    )
    assert invoke(name="my_cli", targets={"test": target}, argv=["--help"]) == 2
    assert "not yet supported" in capsys.readouterr().err.lower()
    assert target.require("unsupported").__self__.calls == 0
