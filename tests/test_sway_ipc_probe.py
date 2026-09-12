from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
PROBE = REPOSITORY / "examples" / "probe_sway_ipc.py"


def test_probe_reaches_fake_connection_after_loading_complete_module_closure(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "i3ipc.py").write_text(
        """\
from types import SimpleNamespace


class Connection:
    def get_tree(self):
        return SimpleNamespace(find_focused=lambda: SimpleNamespace(id=4242))
""",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(fake), str(REPOSITORY / "src"))),
        "SWAYSOCK": "deterministic-test-socket",
    }

    completed = subprocess.run(
        [sys.executable, str(PROBE)],
        cwd=REPOSITORY,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    assert json.loads(lines[0]) == {"focused_con_id": 4242}
    assert lines[-1] == "live_sway=passed"
    assert completed.stderr == ""
