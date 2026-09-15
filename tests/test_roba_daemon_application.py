from __future__ import annotations

import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec
from dix.modules import first_party_module_path


def test_application_sets_the_daemon_owned_config_per_invocation(tmp_path: Path) -> None:
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    for module_id in ("dix/state", "dix/cli", "dix/roba"):
        modules.load_module(first_party_module_path(module_id), module_id=module_id)
    instance = applications.create_instance(
        ApplicationInstanceSpec("daemon", "dix/roba/daemon", {}, tmp_path),
        owner_scope_id="test",
    )
    root = Path(tempfile.mkdtemp(prefix="dix-roba-"))
    config = {
        "daemon_id": "application-test",
        "runtime_root": str(root / "runtime"),
        "logs_root": str(root / "logs"),
        "timeout": 5.0,
    }
    creation = instance.api.require("start")(**config)
    token = asdict(creation).pop("control_token")
    try:
        assert isinstance(token, str) and token
        assert instance.api.require("status")(**config)["daemon_id"] == "application-test"
    finally:
        instance.api.require("stop")(**config)
        shutil.rmtree(root, ignore_errors=True)
