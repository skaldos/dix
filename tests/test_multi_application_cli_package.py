from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
VERIFY = REPOSITORY / "examples" / "launchers" / "verify_my_cli_wheel.py"


def test_wheel_installed_cli_module_builds_and_runs_launcher(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(VERIFY), str(tmp_path)],
        cwd=REPOSITORY,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "base-without-typer=ok" in completed.stdout
    assert "wheel-cli-module=ok" in completed.stdout
    assert "Hello Wheel" in completed.stdout
