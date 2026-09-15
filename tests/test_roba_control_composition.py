from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from roba import ContextApi, daemon_status, start_daemon, stop_daemon

from dix.core import CompositionComponent, ModuleComponent, create_core_component_registry
from dix.core.composition import CompositionInstanceSpec
from dix.modules import first_party_module_path

CONTROL_STATE = {
    "control_locator",
    "control_token",
    "owner_token",
}


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


def _config(tmp_path: Path) -> dict[str, object]:
    root = Path(tempfile.mkdtemp(prefix="dix-r-"))
    return {
        "daemon_id": "control-test",
        "runtime_root": str(root / "runtime"),
        "logs_root": str(root / "logs"),
        "timeout": 5.0,
    }


def _environment(config: dict[str, object]) -> dict[str, str]:
    return {
        "ROBA_RUNTIME_ROOT": str(config["runtime_root"]),
        "ROBA_LOGS_ROOT": str(config["logs_root"]),
    }


def test_bootstrap_attaches_to_running_daemon_and_creates_control_registry(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    config = _config(tmp_path)
    assert instance.api.require("set")(config) is True
    creation = start_daemon(
        str(config["daemon_id"]),
        timeout=5,
        env=_environment(config),
    )
    try:
        result = instance.api.require("bootstrap")(
            control_locator=str(creation.control_locator),
            control_token=creation.control_token,
        )
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
        assert result["control_context"] == "dix.control"
        assert result["root_socket_id"] == "admin"
        assert Path(str(result["root_socket"])).is_socket()

        credentials = instance.api.require("control_credentials")()
        assert set(credentials) == CONTROL_STATE
        assert credentials["control_locator"] == result["control_locator"]
        assert credentials["control_token"] == result["control_token"]
        assert credentials["owner_token"] == result["control_owner_token"]
    finally:
        assert daemon_status(
            daemon=f"id:{config['daemon_id']}",
            env=_environment(config),
        )["daemon_id"] == config["daemon_id"]
        stop_daemon(
            daemon=f"id:{config['daemon_id']}",
            env=_environment(config),
        )


def test_attach_failure_does_not_stop_already_running_daemon(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance(tmp_path)
    config = _config(tmp_path)
    assert instance.api.require("set")(config) is True
    creation = start_daemon(
        str(config["daemon_id"]),
        timeout=5,
        env=_environment(config),
    )

    original_socket_create = ContextApi.socket_create

    def fail_root_socket(self: ContextApi, **kwargs: object) -> dict[str, object]:
        result = original_socket_create(self, **kwargs)
        if kwargs.get("socket_id") == "admin":
            raise RuntimeError("injected attach root socket failure")
        return result

    monkeypatch.setattr(ContextApi, "socket_create", fail_root_socket)
    try:
        with pytest.raises(RuntimeError, match="injected attach root socket failure"):
            instance.api.require("bootstrap")(
                control_locator=str(creation.control_locator),
                control_token=creation.control_token,
            )

        status = daemon_status(
            daemon=f"id:{config['daemon_id']}",
            env=_environment(config),
        )
        assert status["daemon_id"] == config["daemon_id"]
    finally:
        stop_daemon(
            daemon=f"id:{config['daemon_id']}",
            env=_environment(config),
        )
