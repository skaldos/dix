from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from dix.core import CompositionComponent, ModuleComponent, create_core_component_registry
from dix.core.composition import CompositionInstanceSpec
from dix.modules import first_party_module_path
from roba import ContextApi, RobaClient, stop_daemon


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


def test_bootstrap_creates_ephemeral_control_context_and_tokenless_root_socket(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    config = _config(tmp_path)
    assert instance.api.require("set")(config) is True

    result = instance.api.require("bootstrap")()
    try:
        assert set(result) == {
            "daemon_id",
            "control_locator",
            "control_socket",
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

        owner = RobaClient(timeout=5).context(
            locator=str(result["control_context_locator"]),
            token=str(result["control_owner_token"]),
        )
        assert owner.state() == {
            "control_locator": result["control_locator"],
            "control_token": result["control_token"],
            "owner_token": result["control_owner_token"],
        }
        assert owner.socket_info(socket_id="admin")["access"] == {
            "context": ["read"]
        }

        tokenless_root = RobaClient(timeout=5).context(
            locator=f"unix:{result['root_socket']}",
            token=None,
        )
        assert tokenless_root.get("control_locator") == result["control_locator"]
        assert tokenless_root.get("owner_token") == result["control_owner_token"]
    finally:
        stop_daemon(
            daemon=f"id:{result['daemon_id']}",
            env={
                "ROBA_RUNTIME_ROOT": config["runtime_root"],
                "ROBA_LOGS_ROOT": config["logs_root"],
            },
        )


def test_bootstrap_stops_its_new_daemon_when_control_creation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _instance(tmp_path)
    config = _config(tmp_path)
    assert instance.api.require("set")(config) is True

    original_socket_create = ContextApi.socket_create

    def fail_root_socket(self: ContextApi, **kwargs: object) -> dict[str, object]:
        if kwargs.get("socket_id") == "admin":
            raise RuntimeError("injected root socket failure")
        return original_socket_create(self, **kwargs)

    monkeypatch.setattr(ContextApi, "socket_create", fail_root_socket)
    with pytest.raises(RuntimeError, match="injected root socket failure"):
        instance.api.require("bootstrap")()

    assert not (Path(str(config["runtime_root"])) / "daemons" / "control-test").exists()
