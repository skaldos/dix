from __future__ import annotations

import inspect
from pathlib import Path

from dix.core.application import ApplicationApi, ApplicationFunctionDescriptor, ApplicationRuntimeContext

import dix_sway_groups_application_runtime_test_import as runtime_module


class _Groups:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def require(self, function_id: str):
        def call(*args: object) -> object:
            self.calls.append((function_id, args))
            return {"create": None, "add": True, "remove": False, "show": [4], "list": {"work": [4]}}[
                function_id
            ]

        return call


def _context() -> ApplicationRuntimeContext:
    return ApplicationRuntimeContext(
        instance_id="groups",
        application_id="dix/sway/groups",
        module_id="dix/sway",
        module_root=Path("."),
        application_root=Path("."),
        config_base_dir=Path("."),
        owner_scope_id="test",
    )


def test_application_exposes_group_composition_without_new_business_logic() -> None:
    groups = _Groups()
    runtime = runtime_module.Runtime(context=_context(), config={}, groups=groups)

    assert runtime.create("work") is None
    assert runtime.add("work") is True
    assert runtime.remove("work") is False
    assert runtime.show("work") == [4]
    assert runtime.list() == {"work": [4]}
    assert groups.calls == [
        ("create", ("work",)),
        ("add", ("work",)),
        ("remove", ("work",)),
        ("show", ("work",)),
        ("list", ()),
    ]


def _application_api() -> ApplicationApi:
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
        return [4]

    def list_groups() -> dict[str, list[int]]:
        return {"work": [4]}

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


def test_application_api_keeps_exact_five_named_functions() -> None:
    assert {descriptor.id for descriptor in _application_api().functions()} == {
        "create",
        "add",
        "remove",
        "show",
        "list",
    }
