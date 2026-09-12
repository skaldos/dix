from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec, ApplicationRuntimeContext
from dix.modules import first_party_module_path

import dix_sway_runtime_application_runtime_test_import as runtime_module


def _context() -> ApplicationRuntimeContext:
    return ApplicationRuntimeContext(
        instance_id="runtime",
        application_id="dix/sway/runtime",
        module_id="dix/sway",
        module_root=Path("."),
        application_root=Path("."),
        config_base_dir=Path("."),
        owner_scope_id="test",
    )


class _FakeApi:
    def __init__(self, functions: dict[str, object]) -> None:
        self.functions = functions
        self.calls: list[tuple[str, dict[str, object]]] = []

    def require(self, function_id: str):
        function = self.functions[function_id]

        def invoke(**kwargs: object) -> object:
            self.calls.append((function_id, kwargs))
            return function(**kwargs)

        return invoke


def _runtime(*, managed=None, control=None, daemon=None) -> runtime_module.Runtime:
    managed_api = managed or _FakeApi({"start": lambda **kwargs: {"secret": "owner"}})
    control_api = control or _FakeApi(
        {
            "create_context": lambda **kwargs: {"owner_token": "owner"},
            "control_credentials": lambda **kwargs: {"control_token": "control"},
            "context_credentials": lambda **kwargs: {"owner_token": "owner"},
        }
    )
    daemon_api = daemon or _FakeApi(
        {
            "status": lambda **kwargs: {"daemon_id": "default", "running": True},
            "stop": lambda **kwargs: {"stopped": True},
        }
    )
    return runtime_module.Runtime(
        context=_context(),
        config={},
        managed=managed_api,
        control=control_api,
        daemon=daemon_api,
    )


def test_runtime_application_is_declared_with_fixed_lifecycle_and_dependencies(tmp_path: Path) -> None:
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    for module_id in ("dix/state", "dix/cli", "dix/roba", "dix/sway"):
        modules.load_module(first_party_module_path(module_id), module_id=module_id)

    application = applications.create_instance(
        ApplicationInstanceSpec("runtime", "dix/sway/runtime", {}, tmp_path),
        owner_scope_id="test",
    )
    assert {item.id for item in application.api.functions()} == {"start", "status", "stop"}
    assert inspect.signature(application.api.require("start")).parameters == {}
    assert inspect.signature(application.api.require("status")).parameters == {}
    assert inspect.signature(application.api.require("stop")).parameters == {}


def test_start_orders_managed_context_and_status_and_returns_no_credentials() -> None:
    events: list[str] = []
    managed = _FakeApi({"start": lambda **kwargs: events.append("managed.start")})
    control = _FakeApi(
        {
            "create_context": lambda **kwargs: events.append("control.create_context"),
            "control_credentials": lambda **kwargs: events.append("control.credentials") or {"token": "x"},
            "context_credentials": lambda **kwargs: events.append("context.credentials") or {"token": "y"},
        }
    )
    daemon = _FakeApi(
        {
            "status": lambda **kwargs: events.append("daemon.status") or {"daemon_id": "default"},
            "stop": lambda **kwargs: events.append("daemon.stop") or {},
        }
    )
    runtime = _runtime(managed=managed, control=control, daemon=daemon)

    result = runtime.start()

    assert events == [
        "managed.start",
        "control.create_context",
        "daemon.status",
        "control.credentials",
        "context.credentials",
    ]
    assert result == {
        "daemon": {"daemon_id": "default"},
        "control_ready": True,
        "context_id": "sway",
        "context_ready": True,
    }
    assert "token" not in repr(result)


def test_status_is_read_only_and_does_not_expose_credentials() -> None:
    runtime = _runtime()
    result = runtime.status()

    assert result["context_id"] == "sway"
    assert result["control_ready"] is True
    assert result["context_ready"] is True
    assert "owner_token" not in repr(result)
    assert "control_token" not in repr(result)
    assert runtime.daemon.calls[0][0] == "status"
    assert [name for name, _ in runtime.daemon.calls] == ["status"]


def test_start_cleans_up_exactly_once_after_context_failure() -> None:
    events: list[str] = []
    managed = _FakeApi({"start": lambda **kwargs: events.append("managed.start")})
    control = _FakeApi(
        {
            "create_context": lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError("context creation failed")
            ),
            "control_credentials": lambda **kwargs: {},
            "context_credentials": lambda **kwargs: {},
        }
    )
    daemon = _FakeApi(
        {
            "status": lambda **kwargs: {},
            "stop": lambda **kwargs: events.append("daemon.stop") or {"stopped": True},
        }
    )
    runtime = _runtime(managed=managed, control=control, daemon=daemon)

    with pytest.raises(RuntimeError, match="context creation failed"):
        runtime.start()

    assert events == ["managed.start", "daemon.stop"]
    assert [name for name, _ in daemon.calls] == ["stop"]


def test_start_does_not_stop_when_managed_start_fails() -> None:
    managed = _FakeApi(
        {"start": lambda **kwargs: (_ for _ in ()).throw(RuntimeError("managed failed"))}
    )
    daemon = _FakeApi({"status": lambda **kwargs: {}, "stop": lambda **kwargs: {}})
    runtime = _runtime(managed=managed, daemon=daemon)

    with pytest.raises(RuntimeError, match="managed failed"):
        runtime.start()

    assert daemon.calls == []


def test_stop_only_delegates_to_daemon_authority() -> None:
    runtime = _runtime()

    assert runtime.stop() == {"stopped": True}
    assert [name for name, _ in runtime.daemon.calls] == ["stop"]
    assert runtime.managed.calls == []
    assert runtime.control.calls == []


def test_start_surfaces_primary_and_cleanup_failure() -> None:
    managed = _FakeApi({"start": lambda **kwargs: {}})
    control = _FakeApi(
        {
            "create_context": lambda **kwargs: (_ for _ in ()).throw(RuntimeError("primary")),
            "control_credentials": lambda **kwargs: {},
            "context_credentials": lambda **kwargs: {},
        }
    )
    daemon = _FakeApi(
        {
            "status": lambda **kwargs: {},
            "stop": lambda **kwargs: (_ for _ in ()).throw(RuntimeError("cleanup")),
        }
    )

    with pytest.raises(RuntimeError, match="primary; cleanup failed: cleanup"):
        _runtime(managed=managed, control=control, daemon=daemon).start()
