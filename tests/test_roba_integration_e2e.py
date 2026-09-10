from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import subprocess
import sys
from pathlib import Path

from dix.bootstrap import build_launcher

REPOSITORY = Path(__file__).resolve().parents[1]
SPEC = REPOSITORY / "examples" / "launchers" / "dix_roba.toml"
_TOKEN = re.compile(r"control_token='([^']+)'")


def _run(launcher: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(launcher), *arguments],
        cwd=REPOSITORY,
        env={**os.environ, "PYTHONPATH": str(REPOSITORY / "src")},
        text=True,
        capture_output=True,
        check=False,
    )


def _token_fingerprint(output: str) -> tuple[str, str]:
    match = _TOKEN.search(output)
    assert match is not None, output
    token = match.group(1)
    return token, hashlib.sha256(token.encode()).hexdigest()


def _config(tmp_path: Path) -> tuple[str, ...]:
    return (
        "--daemon_id", "e2e",
        "--runtime_root", str(tmp_path / "runtime"),
        "--logs_root", str(tmp_path / "logs"),
        "--timeout", "5",
    )


def test_separate_cli_processes_start_status_stop_and_rotate_control_tokens(tmp_path: Path) -> None:
    launcher = build_launcher(SPEC, tmp_path / "dix_roba.py")
    root = Path(tempfile.mkdtemp(prefix="dix-roba-"))
    config = _config(root)

    first = _run(launcher, "daemon", "start", *config)
    assert first.returncode == 0, first.stderr
    first_token, first_fingerprint = _token_fingerprint(first.stdout)
    try:
        status = _run(launcher, "daemon", "status", *config)
        assert status.returncode == 0, status.stderr
        assert "e2e" in status.stdout
    finally:
        stopped = _run(launcher, "daemon", "stop", *config)
    assert stopped.returncode == 0, stopped.stderr
    shutil.rmtree(root, ignore_errors=True)
    assert not (tmp_path / "runtime" / "daemons" / "e2e").exists()

    second = _run(launcher, "daemon", "start", *config)
    assert second.returncode == 0, second.stderr
    second_token, second_fingerprint = _token_fingerprint(second.stdout)
    try:
        assert first_fingerprint != second_fingerprint
        for path in (root / "runtime").rglob("*"):
            if path.is_file():
                assert first_token not in path.read_text(errors="ignore")
                assert second_token not in path.read_text(errors="ignore")
        for path in (root / "logs").rglob("*"):
            if path.is_file():
                assert first_token not in path.read_text(errors="ignore")
                assert second_token not in path.read_text(errors="ignore")
    finally:
        stopped = _run(launcher, "daemon", "stop", *config)
    assert stopped.returncode == 0, stopped.stderr
    shutil.rmtree(root, ignore_errors=True)
