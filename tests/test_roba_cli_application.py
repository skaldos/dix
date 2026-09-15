from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dix.bootstrap import build_launcher

REPOSITORY = Path(__file__).resolve().parents[1]
SPEC = REPOSITORY / "examples" / "launchers" / "dix_roba.toml"


def _run(launcher: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(launcher), *arguments],
        cwd=REPOSITORY,
        env={**os.environ, "PYTHONPATH": str(REPOSITORY / "src")},
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_projects_named_daemon_options_and_uses_explicit_config(tmp_path: Path) -> None:
    launcher = build_launcher(SPEC, tmp_path / "dix_roba.py")
    help_result = _run(launcher, "daemon", "start", "--help")
    assert help_result.returncode == 0
    for option in ("--daemon_id", "--runtime_root", "--logs_root", "--timeout"):
        assert option in help_result.stdout
    assert "DIX_ROBA_DAEMON_START_DAEMON_ID" in help_result.stdout

    control_help = _run(launcher, "control", "create_context", "--help")
    assert control_help.returncode == 0, control_help.stderr
    for option in (
        "--context_id",
        "--daemon_id",
        "--runtime_root",
        "--logs_root",
        "--timeout",
    ):
        assert option in control_help.stdout
    assert "DIX_ROBA_CONTROL_CREATE_CONTEXT" in control_help.stdout

    bootstrap_help = _run(launcher, "control", "bootstrap", "--help")
    assert bootstrap_help.returncode == 0, bootstrap_help.stderr
    for option in ("--control_locator", "--control_token", "--daemon_id"):
        assert option in bootstrap_help.stdout

    managed_help = _run(launcher, "managed", "start", "--help")
    assert managed_help.returncode == 0, managed_help.stderr
    for option in ("--daemon_id", "--runtime_root", "--logs_root", "--timeout"):
        assert option in managed_help.stdout

    root = Path(tempfile.mkdtemp(prefix="dix-roba-"))
    config = (
        "--daemon_id", "cli-test",
        "--runtime_root", str(root / "runtime"),
        "--logs_root", str(root / "logs"),
        "--timeout", "5",
    )
    started = _run(launcher, "daemon", "start", *config)
    assert started.returncode == 0, started.stderr
    try:
        status = _run(launcher, "daemon", "status", *config)
        assert status.returncode == 0, status.stderr
        assert "cli-test" in status.stdout
    finally:
        stopped = _run(launcher, "daemon", "stop", *config)
    assert stopped.returncode == 0, stopped.stderr
    shutil.rmtree(root, ignore_errors=True)
