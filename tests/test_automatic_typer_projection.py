from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

from dix.core import CompositionComponent, ModuleComponent, create_core_component_registry
from dix.core.application import (
    ApplicationDefinition,
    ApplicationDescriptor,
    ApplicationFunctionDescriptor,
)
from dix.core.composition import CompositionInstanceSpec
from dix.core.function import derive_function_contract
from dix.core.module import ModuleDescriptor

REPOSITORY = Path(__file__).resolve().parents[1]
CLI_MODULE = REPOSITORY / "examples" / "modules" / "dix" / "core" / "cli"


def typer_runtime(tmp_path: Path):
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    modules.load_module(CLI_MODULE, module_id="dix/core/cli")
    compositions = registry.require("composition", CompositionComponent)
    return compositions.create_instance(
        CompositionInstanceSpec("cli", "dix/core/cli/typer_cli", {}, tmp_path),
        owner_scope_id="test",
    )


def application_descriptor(tmp_path: Path, **functions) -> ApplicationDescriptor:
    definition = ApplicationDefinition(
        id="test/tool",
        local_id="tool",
        module_id="test",
        module_root=tmp_path,
        application_root=tmp_path,
        spec_path=tmp_path / "app.toml",
        runtime_path=tmp_path / "runtime.py",
        functions={},
    )
    descriptors = []
    for function_id, function in sorted(functions.items()):
        signature = inspect.signature(function)
        descriptors.append(
            ApplicationFunctionDescriptor(
                id=function_id,
                application_id=definition.id,
                source="local",
                origin=None,
                signature=signature,
                return_annotation=signature.return_annotation,
                docstring=inspect.getdoc(function),
                contract=derive_function_contract(definition.id, function_id, signature),
            )
        )
    return ApplicationDescriptor(
        definition=definition,
        functions=tuple(descriptors),
        module=ModuleDescriptor(
            id="test",
            root=tmp_path,
            artifact_digest="0" * 64,
            loaded=True,
            composition_ids=(),
            application_ids=(definition.id,),
        ),
    )


def test_auto_projection_describes_help_and_invokes_without_explicit_cli_files(
    tmp_path: Path,
    capsys,
) -> None:
    cli = typer_runtime(tmp_path)
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def render(positional: str, /, count: int = 2, *, upper: bool = False) -> str:
        """Render a value."""
        return positional

    descriptor = application_descriptor(tmp_path, render=render)

    described = cli.api.describe_application(descriptor=descriptor)
    assert json.loads(json.dumps(described)) == described
    assert described["commands"]["render"]["parameters"][0]["kind"] == "POSITIONAL_ONLY"

    def invoke(function_id, args, kwargs):
        calls.append((function_id, tuple(args), dict(kwargs)))
        value = str(args[0])
        return (value.upper() if kwargs["upper"] else value) * int(kwargs["count"])

    assert cli.api.invoke_application(
        descriptor=descriptor,
        invoke=invoke,
        argv=["render", "--help"],
    ) == 0
    help_output = capsys.readouterr()
    assert "--positional" in help_output.out
    assert "--count" in help_output.out
    assert "--upper" in help_output.out
    assert "env var" not in help_output.out.lower()
    assert calls == []

    assert cli.api.invoke_application(
        descriptor=descriptor,
        invoke=invoke,
        argv=["render", "--upper", "false"],
    ) == 2
    assert "missing option '--positional'" in capsys.readouterr().err.lower()
    assert calls == []

    assert cli.api.invoke_application(
        descriptor=descriptor,
        invoke=invoke,
        argv=["render", "--positional", "x", "--upper", "yes"],
    ) == 2
    assert "expected 'true' or 'false'" in capsys.readouterr().err
    assert calls == []

    assert cli.api.invoke_application(
        descriptor=descriptor,
        invoke=invoke,
        argv=["render", "--positional", "x", "--upper", "false"],
    ) == 0
    assert capsys.readouterr().out == "xx\n"
    assert calls == [("render", ("x",), {"count": 2, "upper": False})]

    assert cli.api.invoke_application(
        descriptor=descriptor,
        invoke=invoke,
        argv=["render", "--positional", "x", "--upper", "true", "--count", "1"],
    ) == 0
    assert capsys.readouterr().out == "X\n"


def test_auto_projection_has_stable_scalar_json_none_and_error_output(
    tmp_path: Path,
    capsys,
) -> None:
    cli = typer_runtime(tmp_path)

    def number() -> int:
        return 1

    def flag() -> bool:
        return True

    def payload() -> dict[str, object]:
        return {}

    def empty() -> None:
        return None

    def unsupported() -> object:
        return object()

    descriptor = application_descriptor(
        tmp_path,
        number=number,
        flag=flag,
        payload=payload,
        empty=empty,
        unsupported=unsupported,
    )
    outputs = {
        "number": 7,
        "flag": False,
        "payload": {"z": [2, 1], "a": True},
        "empty": None,
        "unsupported": object(),
    }

    def invoke(function_id, args, kwargs):
        return outputs[function_id]

    for command, expected in (
        ("number", "7\n"),
        ("flag", "false\n"),
        ("payload", '{"a":true,"z":[2,1]}\n'),
        ("empty", ""),
    ):
        assert cli.api.invoke_application(
            descriptor=descriptor, invoke=invoke, argv=[command]
        ) == 0
        assert capsys.readouterr().out == expected

    assert cli.api.invoke_application(
        descriptor=descriptor,
        invoke=invoke,
        argv=["unsupported"],
    ) == 1
    error = capsys.readouterr()
    assert error.out == ""
    assert "unsupported output type" in error.err


def test_auto_projection_rejects_fallback_and_variadic_inputs(tmp_path: Path, capsys) -> None:
    cli = typer_runtime(tmp_path)

    def fallback(value: Any) -> str:
        return str(value)

    descriptor = application_descriptor(tmp_path, fallback=fallback)
    assert cli.api.invoke_application(
        descriptor=descriptor,
        invoke=lambda function_id, args, kwargs: None,
        argv=[],
    ) == 2
    assert "fallback_any" in capsys.readouterr().err

    def variadic(*values: str) -> str:
        return "".join(values)

    descriptor = application_descriptor(tmp_path, variadic=variadic)
    assert cli.api.invoke_application(
        descriptor=descriptor,
        invoke=lambda function_id, args, kwargs: None,
        argv=[],
    ) == 2
    assert "variadic" in capsys.readouterr().err
