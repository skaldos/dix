from __future__ import annotations

import tempfile
from pathlib import Path

from roba import start_daemon, stop_daemon

from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec
from dix.modules import first_party_module_path


def _application(tmp_path: Path):
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    for module_id in ("dix/state", "dix/cli", "dix/roba"):
        modules.load_module(first_party_module_path(module_id), module_id=module_id)
    return applications.create_instance(
        ApplicationInstanceSpec("control", "dix/roba/control", {}, tmp_path),
        owner_scope_id="test",
    )


def test_control_application_exposes_four_functions_with_invocation_config(
    tmp_path: Path,
) -> None:
    application = _application(tmp_path)
    assert {item.id for item in application.api.functions()} == {
        "bootstrap",
        "control_credentials",
        "create_context",
        "context_credentials",
    }
    root = Path(tempfile.mkdtemp(prefix="dix-r-"))
    config = {
        "daemon_id": "application-control-test",
        "runtime_root": str(root / "runtime"),
        "logs_root": str(root / "logs"),
        "timeout": 5.0,
    }
    creation = start_daemon(
        str(config["daemon_id"]),
        timeout=5,
        env={
            "ROBA_RUNTIME_ROOT": str(config["runtime_root"]),
            "ROBA_LOGS_ROOT": str(config["logs_root"]),
        },
    )
    bootstrap = application.api.require("bootstrap")(
        control_locator=str(creation.control_locator),
        control_token=creation.control_token,
        **config,
    )
    try:
        credentials = application.api.require("control_credentials")(**config)
        assert credentials["control_token"] == bootstrap["control_token"]
        created = application.api.require("create_context")(
            context_id="app-test01",
            **config,
        )
        rebound = application.api.require("context_credentials")(
            context_id="app-test01",
            **config,
        )
        assert rebound["owner_token"] == created["owner_token"]
    finally:
        stop_daemon(
            daemon=f"id:{config['daemon_id']}",
            env={
                "ROBA_RUNTIME_ROOT": str(config["runtime_root"]),
                "ROBA_LOGS_ROOT": str(config["logs_root"]),
            },
        )
