from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import tempfile

import pytest

from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec, ApplicationRuntimeContext
from dix.modules import first_party_module_path
from roba import stop_daemon


_RUNTIME_PATH = (
    Path(__file__).resolve().parents[1]
    / "modules/dix/roba/apps/managed/runtime.py"
)
_RUNTIME_SPEC = importlib.util.spec_from_file_location("dix_managed_test_runtime", _RUNTIME_PATH)
assert _RUNTIME_SPEC is not None and _RUNTIME_SPEC.loader is not None
_RUNTIME_MODULE = importlib.util.module_from_spec(_RUNTIME_SPEC)
_RUNTIME_SPEC.loader.exec_module(_RUNTIME_MODULE)
ManagedRuntime = _RUNTIME_MODULE.Runtime


def _application(tmp_path: Path):
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    for module_id in ("dix/state", "dix/cli", "dix/roba"):
        modules.load_module(first_party_module_path(module_id), module_id=module_id)
    return applications.create_instance(
        ApplicationInstanceSpec("managed", "dix/roba/managed", {}, tmp_path),
        owner_scope_id="test",
    )


def test_managed_application_starts_and_attaches_one_dix_owned_daemon(
    tmp_path: Path,
) -> None:
    application = _application(tmp_path)
    root = Path(tempfile.mkdtemp(prefix="dix-r-"))
    config = {
        "daemon_id": "managed-test",
        "runtime_root": str(root / "runtime"),
        "logs_root": str(root / "logs"),
        "timeout": 5.0,
    }
    result = application.api.require("start")(**config)
    try:
        assert set(result) == {
            "daemon_id",
            "control_locator",
            "control_context",
            "control_context_locator",
            "control_owner_token",
            "root_socket",
            "root_socket_id",
            "control_token",
        }
        assert result["daemon_id"] == "managed-test"
        assert result["control_context"] == "dix.control"
        assert Path(str(result["root_socket"])).is_socket()
    finally:
        stop_daemon(
            daemon="id:managed-test",
            env={
                "ROBA_RUNTIME_ROOT": str(config["runtime_root"]),
                "ROBA_LOGS_ROOT": str(config["logs_root"]),
            },
        )


@dataclass
class _FakeApi:
    functions: dict[str, object]

    def require(self, function_id: str):
        return self.functions[function_id]


def _context() -> ApplicationRuntimeContext:
    return ApplicationRuntimeContext(
        instance_id="managed",
        application_id="dix/roba/managed",
        module_id="dix/roba",
        module_root=Path("."),
        application_root=Path("."),
        config_base_dir=Path("."),
        owner_scope_id="test",
    )


def test_managed_failure_stops_only_the_daemon_started_by_this_call() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def start(**kwargs: object) -> object:
        calls.append(("start", kwargs))
        return type("Creation", (), {
            "control_locator": "unix:/tmp/control.sock",
            "control_token": "secret",
        })()

    def stop(**kwargs: object) -> dict[str, object]:
        calls.append(("stop", kwargs))
        return {}

    def bootstrap(**kwargs: object) -> object:
        calls.append(("bootstrap", kwargs))
        raise RuntimeError("injected bootstrap failure")

    runtime = ManagedRuntime(
        context=_context(),
        config={},
        daemon=_FakeApi({"start": start, "stop": stop}),
        control=_FakeApi({"bootstrap": bootstrap}),
    )
    invocation = {
        "daemon_id": "owned",
        "runtime_root": "/tmp/runtime",
        "logs_root": "/tmp/logs",
        "timeout": 5.0,
    }
    with pytest.raises(RuntimeError, match="injected bootstrap failure"):
        runtime.start(**invocation)
    assert [name for name, _ in calls] == ["start", "bootstrap", "stop"]
    assert calls[-1][1] == invocation


def test_managed_failure_before_start_does_not_stop_any_daemon() -> None:
    calls: list[str] = []

    def start(**kwargs: object) -> object:
        calls.append("start")
        raise RuntimeError("injected start failure")

    def stop(**kwargs: object) -> dict[str, object]:
        calls.append("stop")
        return {}

    runtime = ManagedRuntime(
        context=_context(),
        config={},
        daemon=_FakeApi({"start": start, "stop": stop}),
        control=_FakeApi({}),
    )
    with pytest.raises(RuntimeError, match="injected start failure"):
        runtime.start()
    assert calls == ["start"]
