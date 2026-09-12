from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dix.bootstrap import build_launcher


REPOSITORY = Path(__file__).resolve().parents[1]
SPEC = REPOSITORY / "examples" / "launchers" / "dix_sway.toml"


def _environment(home: Path, fake: Path) -> dict[str, str]:
    inherited = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("ROBA_")
    }
    return {
        **inherited,
        "HOME": str(home),
        "PYTHONPATH": os.pathsep.join((str(fake), str(REPOSITORY / "src"))),
        "SWAYSOCK": "deterministic-test-socket",
        "DIX_TEST_FOCUS": "731",
    }


def _run(
    launcher: Path,
    environment: dict[str, str],
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(launcher), *arguments],
        cwd=REPOSITORY,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _assert_secret_free(completed: subprocess.CompletedProcess[str]) -> None:
    output = f"{completed.stdout}\n{completed.stderr}"
    assert "control_token" not in output
    assert "owner_token" not in output


def test_sway_runtime_is_explicit_ephemeral_and_restarts_empty(tmp_path: Path) -> None:
    launcher = build_launcher(SPEC, tmp_path / "dix_sway.py")
    home = Path(tempfile.mkdtemp(prefix="dix-sway-e2e-", dir="/tmp"))
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "i3ipc.py").write_text(
        """\
import os
from types import SimpleNamespace


class Connection:
    def get_tree(self):
        focused = int(os.environ["DIX_TEST_FOCUS"])
        return SimpleNamespace(find_focused=lambda: SimpleNamespace(id=focused))
""",
        encoding="utf-8",
    )
    environment = _environment(home, fake)
    runtime_root = home / ".roba" / "runtime"
    running = False

    try:
        before_status = _run(launcher, environment, "runtime", "status")
        _assert_secret_free(before_status)
        assert before_status.returncode != 0
        assert not runtime_root.exists()

        before_groups = _run(launcher, environment, "group", "list")
        _assert_secret_free(before_groups)
        assert before_groups.returncode != 0
        assert not runtime_root.exists()

        started = _run(launcher, environment, "runtime", "start")
        _assert_secret_free(started)
        assert started.returncode == 0, started.stderr
        assert "context_id" in started.stdout
        assert "sway" in started.stdout
        running = True

        duplicate_start = _run(launcher, environment, "runtime", "start")
        _assert_secret_free(duplicate_start)
        assert duplicate_start.returncode != 0

        status = _run(launcher, environment, "runtime", "status")
        _assert_secret_free(status)
        assert status.returncode == 0, status.stderr
        assert "context_ready" in status.stdout

        create = _run(launcher, environment, "group", "create", "--group", "work")
        _assert_secret_free(create)
        assert create.returncode == 0, create.stderr
        add = _run(launcher, environment, "group", "add", "--group", "work")
        _assert_secret_free(add)
        assert add.returncode == 0, add.stderr
        listed = _run(launcher, environment, "group", "list")
        _assert_secret_free(listed)
        assert listed.returncode == 0, listed.stderr
        assert listed.stdout.strip() == "{'work': [731]}"

        stopped = _run(launcher, environment, "runtime", "stop")
        _assert_secret_free(stopped)
        assert stopped.returncode == 0, stopped.stderr
        running = False
        assert not (runtime_root / "daemons" / "default").exists()

        after_status = _run(launcher, environment, "runtime", "status")
        _assert_secret_free(after_status)
        assert after_status.returncode != 0
        after_groups = _run(launcher, environment, "group", "list")
        _assert_secret_free(after_groups)
        assert after_groups.returncode != 0

        restarted = _run(launcher, environment, "runtime", "start")
        _assert_secret_free(restarted)
        assert restarted.returncode == 0, restarted.stderr
        running = True
        empty = _run(launcher, environment, "group", "list")
        _assert_secret_free(empty)
        assert empty.returncode == 0, empty.stderr
        assert empty.stdout.strip() == "{}"

        stopped_again = _run(launcher, environment, "runtime", "stop")
        _assert_secret_free(stopped_again)
        assert stopped_again.returncode == 0, stopped_again.stderr
        running = False
        assert not (runtime_root / "daemons" / "default").exists()
    finally:
        if running:
            cleanup = _run(launcher, environment, "runtime", "stop")
            _assert_secret_free(cleanup)
        shutil.rmtree(home, ignore_errors=True)
