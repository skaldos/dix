from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
ENTRY = REPOSITORY / "examples/launchers/dix_sway_navigation.py"

FAKE = '''\nimport json, os\nclass _Node:\n    def __init__(self, ident): self.id = ident\nclass _Tree:\n    def _state(self): return json.loads(open(os.environ["DIX_SWAY_FAKE_STATE"]).read())\n    def find_focused(self): return _Node(self._state()["focused"])\n    def leaves(self): return [_Node(x) for x in self._state()["live"]]\nclass _Reply:\n    success = True\n    error = None\nclass Connection:\n    def get_tree(self): return _Tree()\n    def command(self, command):\n        path = os.environ["DIX_SWAY_FAKE_STATE"]\n        state = json.loads(open(path).read())\n        if command.startswith("focus "):\n            state["commands"].append(command)\n            if state["steps"]: state["focused"] = state["steps"].pop(0)\n        elif command.startswith("[con_id="):\n            state["commands"].append(command)\n            state["focused"] = int(command.split("=",1)[1].split("]",1)[0])\n        open(path,"w").write(json.dumps(state))\n        return [_Reply()]\n'''


def _run(tmp_path: Path, direction: str | None, projection: bytes | None = b"1 3\n", *, set_env: bool = True):
    fake = tmp_path / "fake"; fake.mkdir(exist_ok=True)
    (fake / "i3ipc.py").write_text(FAKE)
    state = tmp_path / "ipc.json"
    state.write_text(json.dumps({"focused": 1, "live": [1, 2, 3], "steps": [2, 3], "commands": []}))
    projection_path = tmp_path / "members.txt"
    if projection is not None: projection_path.write_bytes(projection)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(fake), str(REPOSITORY / "src")])
    env["DIX_SWAY_FAKE_STATE"] = str(state)
    if set_env: env["DIX_SWAY_ACTIVE_MEMBERS_FILE"] = str(projection_path)
    else: env.pop("DIX_SWAY_ACTIVE_MEMBERS_FILE", None)
    args = [sys.executable, str(ENTRY)] + ([] if direction is None else [direction])
    completed = subprocess.run(args, cwd=REPOSITORY, env=env, text=True, capture_output=True)
    return completed, json.loads(state.read_text())


def test_all_four_directions_use_productive_group_loop_without_heavy_modules(tmp_path: Path) -> None:
    for direction in ("left", "right", "up", "down"):
        run_path = tmp_path / direction; run_path.mkdir()
        completed, state = _run(run_path, direction)
        assert completed.returncode == 0, completed.stderr
        result = json.loads(completed.stdout)
        assert result["direction"] == direction and result["focused_id"] == 3
        assert state["commands"] == [f"focus {direction}", f"focus {direction}"]


def test_missing_or_empty_explicit_projection_uses_one_basic_step(tmp_path: Path) -> None:
    for projection in (None, b"\n"):
        run_path = tmp_path / ("missing" if projection is None else "empty"); run_path.mkdir()
        completed, state = _run(run_path, "right", projection)
        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout) == {"changed": True, "direction": "right", "focused_id": 2, "origin_id": 1}
        assert state["commands"] == ["focus right"]


def test_bad_direction_or_configuration_fails_before_ipc(tmp_path: Path) -> None:
    for direction, configured in ((None, True), ("next", True), ("left", False)):
        run_path = tmp_path / f"case-{direction}-{configured}"; run_path.mkdir()
        completed, state = _run(run_path, direction, set_env=configured)
        assert completed.returncode != 0 and completed.stderr
        assert state["commands"] == []


def test_corrupt_projection_fails_before_ipc(tmp_path: Path) -> None:
    completed, state = _run(tmp_path, "left", b"01\n")
    assert completed.returncode == 1
    assert "Error:" in completed.stderr
    assert state["commands"] == []
