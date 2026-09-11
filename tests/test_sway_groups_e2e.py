from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from roba import start_daemon, stop_daemon

from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec
from dix.modules import first_party_module_path


REPOSITORY = Path(__file__).resolve().parents[1]


def _setup_control(home: Path, runtime_root: Path, logs_root: Path):
    environment = {
        "ROBA_RUNTIME_ROOT": str(runtime_root),
        "ROBA_LOGS_ROOT": str(logs_root),
    }
    creation = start_daemon("default", env=environment)
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    for module_id in ("dix/state", "dix/cli", "dix/roba", "dix/sway"):
        modules.load_module(first_party_module_path(module_id), module_id=module_id)
    control = applications.create_instance(
        ApplicationInstanceSpec("control", "dix/roba/control", {}, REPOSITORY),
        owner_scope_id="setup",
    )
    control.api.require("bootstrap")(
        control_locator=str(creation.control_locator),
        control_token=creation.control_token,
        daemon_id="default",
        runtime_root=str(runtime_root),
        logs_root=str(logs_root),
        timeout=5.0,
    )
    control.api.require("create_context")(
        context_id="sway",
        daemon_id="default",
        runtime_root=str(runtime_root),
        logs_root=str(logs_root),
        timeout=5.0,
    )
    return creation, environment


_CLI = r'''
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import i3ipc

from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec
from dix.modules import first_party_module_path


class _Connection:
    def get_tree(self):
        focused = int(os.environ["DIX_TEST_FOCUS"])
        return SimpleNamespace(find_focused=lambda: SimpleNamespace(id=focused))


i3ipc.Connection = _Connection
registry = create_core_component_registry()
modules = registry.require("module", ModuleComponent)
applications = registry.require("application", ApplicationComponent)
for module_id in ("dix/state", "dix/cli", "dix/roba", "dix/sway"):
    modules.load_module(first_party_module_path(module_id), module_id=module_id)
application = applications.create_instance(
    ApplicationInstanceSpec("cli", "dix/sway/cli", {}, Path.cwd()),
    owner_scope_id=os.environ["DIX_TEST_OWNER"],
)
raise SystemExit(application.api.require("main")(os.sys.argv[1:]))
'''


def _cli(home: Path, command: tuple[str, ...], *, focus: int, owner: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _CLI, *command],
        cwd=REPOSITORY,
        env={
            **os.environ,
            "HOME": str(home),
            "PYTHONPATH": str(REPOSITORY / "src"),
            "SWAYSOCK": "",
            "DIX_TEST_FOCUS": str(focus),
            "DIX_TEST_OWNER": owner,
        },
        text=True,
        capture_output=True,
        check=False,
    )


def test_separate_cli_processes_share_roba_groups_with_fake_ipc(tmp_path: Path) -> None:
    root = Path(tempfile.mkdtemp(prefix="dix-sway-", dir="/tmp"))
    home = root / "home"
    runtime_root = home / ".roba" / "runtime"
    logs_root = home / ".roba" / "logs"
    home.mkdir(parents=True)
    try:
        creation, environment = _setup_control(home, runtime_root, logs_root)
        for command, focus, owner in (
            (("group", "create", "--group", "work"), 0, "create"),
            (("group", "add", "--group", "work"), 101, "add-one"),
            (("group", "add", "--group", "work"), 202, "add-two"),
        ):
            completed = _cli(home, command, focus=focus, owner=owner)
            assert completed.returncode == 0, completed.stderr

        listed = _cli(home, ("group", "list"), focus=0, owner="list")
        assert listed.returncode == 0, listed.stderr
        assert listed.stdout.strip() == "{'work': [101, 202]}"
    finally:
        if "environment" in locals():
            stop_daemon(daemon="id:default", env=environment)
        shutil.rmtree(root, ignore_errors=True)
