from __future__ import annotations

import inspect
from pathlib import Path

from dix.core.application import ApplicationApi, ApplicationFunctionDescriptor, ApplicationRuntimeContext

import dix_sway_cli_application_runtime_test_import as runtime_module
import dix_typer_runtime_test_import as typer_module


def _context() -> ApplicationRuntimeContext:
    return ApplicationRuntimeContext(
        instance_id="cli",
        application_id="dix/sway/cli",
        module_id="dix/sway",
        module_root=Path("."),
        application_root=Path("."),
        config_base_dir=Path("."),
        owner_scope_id="test",
    )


def _groups_api() -> ApplicationApi:
    def create(*, group: str) -> None:
        del group

    def add(*, group: str) -> bool:
        del group
        return True

    def remove(*, group: str) -> bool:
        del group
        return False

    def show(*, group: str) -> list[int]:
        del group
        return [8]

    def list_groups() -> dict[str, list[int]]:
        return {"work": [8]}

    functions = {
        "create": create,
        "add": add,
        "remove": remove,
        "show": show,
        "list": list_groups,
    }
    descriptors = {
        name: ApplicationFunctionDescriptor(
            id=name,
            application_id="dix/sway/groups",
            source="local",
            origin=None,
            signature=inspect.signature(function),
            return_annotation=inspect.signature(function).return_annotation,
            docstring=name,
        )
        for name, function in functions.items()
    }
    return ApplicationApi(functions, descriptors)


def test_cli_application_projects_group_api_through_shared_typer(capsys) -> None:
    typer = typer_module.Runtime(context=_context(), config={})
    class TyperApi:
        def require(self, function_id: str):
            assert function_id == "invoke"
            return typer.invoke

    runtime = runtime_module.Runtime(
        context=_context(),
        config={},
        typer=TyperApi(),
        groups=_groups_api(),
    )

    assert runtime.main(["--help"]) == 0
    output = capsys.readouterr().out
    assert "Usage" in output
    assert "group" in output

    assert runtime.main(["group", "show", "--group", "work"]) == 0
    assert "[8]" in capsys.readouterr().out
