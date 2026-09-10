from __future__ import annotations

import os
import shutil
import tempfile
import subprocess
import sys
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
