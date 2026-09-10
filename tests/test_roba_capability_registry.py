from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from dix.core import CompositionComponent, ModuleComponent, create_core_component_registry
from dix.core.composition import CompositionInstanceSpec
from dix.modules import first_party_module_path
from roba import (
    ContextApi,
    RobaClient,
    TransportError,
    principal_socket,
    start_daemon,
    stop_daemon,
)


def _instance(tmp_path: Path):
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    compositions = registry.require("composition", CompositionComponent)
    for module_id in ("dix/state", "dix/cli", "dix/roba"):
        modules.load_module(first_party_module_path(module_id), module_id=module_id)
    return compositions.create_instance(
        CompositionInstanceSpec("control", "dix/roba/control", {}, tmp_path),
        owner_scope_id="test",
    )


def _config() -> dict[str, object]:
    root = Path(tempfile.mkdtemp(prefix="dix-r-"))
    return {
        "daemon_id": "registry-test",
        "runtime_root": str(root / "runtime"),
        "logs_root": str(root / "logs"),
        "timeout": 5.0,
    }


def _stop(result: dict[str, object], config: dict[str, object]) -> None:
    stop_daemon(
        daemon=f"id:{result['daemon_id']}",
        env={
            "ROBA_RUNTIME_ROOT": str(config["runtime_root"]),
            "ROBA_LOGS_ROOT": str(config["logs_root"]),
        },
    )


def _bootstrap(instance, config: dict[str, object]) -> dict[str, object]:
    creation = start_daemon(
        str(config["daemon_id"]),
        timeout=5,
        env={
            "ROBA_RUNTIME_ROOT": str(config["runtime_root"]),
            "ROBA_LOGS_ROOT": str(config["logs_root"]),
        },
    )
    return instance.api.require("bootstrap")(
        control_locator=str(creation.control_locator),
        control_token=creation.control_token,
    )


def test_managed_context_rebinds_owner_through_scoped_manager_socket(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    config = _config()
    assert instance.api.require("set")(config) is True
    bootstrap = _bootstrap(instance, config)
    try:
        created = instance.api.require("create_context")("test01")
        assert set(created) == {
            "context_id",
            "context_locator",
            "owner_token",
            "manager_socket",
            "manager_socket_id",
        }
        assert created["context_id"] == "test01"
        assert created["manager_socket_id"] == "test01"
        assert str(created["context_locator"]).startswith("unix:")
        assert Path(str(created["manager_socket"])).is_socket()

        credentials = instance.api.require("context_credentials")("test01")
        assert credentials == {
            "context_locator": created["context_locator"],
            "owner_token": created["owner_token"],
        }

        manager = RobaClient(timeout=5).context(
            locator=f"unix:{created['manager_socket']}",
            scope="id:test01",
            token=None,
        )
        assert manager.get("context_locator") == created["context_locator"]
        with pytest.raises(TransportError, match="403"):
            manager.with_scope("id:missing").get("context_locator")
        with pytest.raises(TransportError, match="403"):
            manager.with_scope(None).get("control_locator")

        owner = RobaClient(timeout=5).context(
            locator=str(created["context_locator"]),
            token=str(credentials["owner_token"]),
        )
        assert owner.set("proof", "rebound")["key"] == "proof"
        assert owner.get("proof") == "rebound"

        root = RobaClient(timeout=5).context(
            locator=f"unix:{bootstrap['root_socket']}",
            token=None,
        )
        with pytest.raises(TransportError, match="403"):
            root.with_scope("id:test01").get("context_locator")

        with pytest.raises(Exception, match="409|already exists|conflict"):
            instance.api.require("create_context")("test01")
        assert owner.get("proof") == "rebound"
    finally:
        _stop(bootstrap, config)


@pytest.mark.parametrize("fail_after_create", [False, True])
def test_failed_manager_socket_creation_rolls_back_owned_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_after_create: bool,
) -> None:
    instance = _instance(tmp_path)
    config = _config()
    assert instance.api.require("set")(config) is True
    bootstrap = _bootstrap(instance, config)
    original_socket_create = ContextApi.socket_create

    def fail_manager_socket(self: ContextApi, **kwargs: object) -> dict[str, object]:
        if kwargs.get("socket_id") == "broken01" and not fail_after_create:
            raise RuntimeError("injected manager socket failure")
        result = original_socket_create(self, **kwargs)
        if kwargs.get("socket_id") == "broken01":
            raise RuntimeError("injected manager socket failure")
        return result

    monkeypatch.setattr(ContextApi, "socket_create", fail_manager_socket)
    try:
        with pytest.raises(RuntimeError, match="injected manager socket failure"):
            instance.api.require("create_context")("broken01")

        credentials = instance.api.require("control_credentials")()
        environment = {
            "ROBA_RUNTIME_ROOT": str(config["runtime_root"]),
            "ROBA_LOGS_ROOT": str(config["logs_root"]),
        }
        registry_owner = RobaClient(env=environment, timeout=5).context(
            locator=f"id:dix.control",
            control=str(credentials["control_locator"]),
            token=str(credentials["owner_token"]),
        )
        with pytest.raises(TransportError, match="instance not found"):
            registry_owner.instance_snapshot(instance_id="broken01")
        with pytest.raises(TransportError, match="socket not found"):
            registry_owner.socket_info(socket_id="broken01")

        control = RobaClient(env=environment, timeout=5).control(
            locator=str(credentials["control_locator"]),
            token=str(credentials["control_token"]),
        )
        with pytest.raises(TransportError, match="context not found"):
            control.context_info(context_id="broken01")

        manager_path = principal_socket(
            "registry-test",
            "dix.control",
            "broken01",
            environment,
        )
        assert not manager_path.exists()
    finally:
        _stop(bootstrap, config)
