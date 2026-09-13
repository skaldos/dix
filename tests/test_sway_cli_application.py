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

    def select(*, group: str) -> bool:
        del group
        return True

    def current() -> str:
        return "work"

    functions = {
        "create": create,
        "add": add,
        "remove": remove,
        "show": show,
        "list": list_groups,
        "select": select,
        "current": current,
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


def _runtime_api() -> ApplicationApi:
    def start() -> dict[str, object]:
        return {"started": True}

    def status() -> dict[str, object]:
        return {"context_id": "sway", "context_ready": True}

    def stop() -> dict[str, object]:
        return {"stopped": True}

    functions = {"start": start, "status": status, "stop": stop}
    descriptors = {
        name: ApplicationFunctionDescriptor(
            id=name,
            application_id="dix/sway/runtime",
            source="local",
            origin=None,
            signature=inspect.signature(function),
            return_annotation=inspect.signature(function).return_annotation,
            docstring=name,
        )
        for name, function in functions.items()
    }
    return ApplicationApi(functions, descriptors)


def _navigation_api() -> ApplicationApi:
    def select(*, node_selector: str) -> bool:
        del node_selector
        return True

    def current() -> str:
        return "basic"

    def left() -> dict[str, object]:
        return {"direction": "left"}

    def right() -> dict[str, object]:
        return {"direction": "right"}

    def up() -> dict[str, object]:
        return {"direction": "up"}

    def down() -> dict[str, object]:
        return {"direction": "down"}

    functions = {
        "select": select,
        "current": current,
        "left": left,
        "right": right,
        "up": up,
        "down": down,
    }
    descriptors = {
        name: ApplicationFunctionDescriptor(
            id=name,
            application_id="dix/sway/navigation",
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
        runtime=_runtime_api(),
        navigation=_navigation_api(),
    )

    assert runtime.main(["--help"]) == 0
    output = capsys.readouterr().out
    assert "Usage" in output
    assert "group" in output
    assert "navigation" in output

    assert runtime.main(["group", "show", "--group", "work"]) == 0
    assert "[8]" in capsys.readouterr().out


def test_cli_application_projects_parameterless_runtime_group() -> None:
    captured: dict[str, object] = {}

    class TyperApi:
        def require(self, function_id: str):
            assert function_id == "invoke"

            def invoke(**kwargs: object) -> int:
                captured.update(kwargs)
                return 0

            return invoke

    runtime = runtime_module.Runtime(
        context=_context(),
        config={},
        typer=TyperApi(),
        groups=_groups_api(),
        runtime=_runtime_api(),
        navigation=_navigation_api(),
    )

    assert runtime.main(["runtime", "status"]) == 0
    targets = captured["targets"]
    assert set(targets) == {"group", "navigation", "runtime"}
    assert [item.id for item in targets["runtime"].functions()] == ["start", "status", "stop"]
    assert all(
        not descriptor.signature.parameters
        for descriptor in targets["runtime"].functions()
    )


def test_cli_projects_navigation_and_visible_environment_options(capsys) -> None:
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
        runtime=_runtime_api(),
        navigation=_navigation_api(),
    )

    assert runtime.main(["navigation", "--help"]) == 0
    output = capsys.readouterr().out
    for command in ("select", "current", "left", "right", "up", "down"):
        assert command in output

    assert runtime.main(["navigation", "select", "--help"]) == 0
    output = capsys.readouterr().out
    assert "--node_selector" in output
    assert "DIX_SWAY_NAVIGATION_SELECT_NODE_SELECTOR" in output

    assert runtime.main(["group", "select", "--help"]) == 0
    output = capsys.readouterr().out
    assert "--group" in output
    assert "DIX_SWAY_GROUP_SELECT_GROUP" in output
