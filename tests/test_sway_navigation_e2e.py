from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from roba import RobaClient, principal_socket

from dix.bootstrap import build_launcher


REPOSITORY = Path(__file__).resolve().parents[1]
SPEC = REPOSITORY / "examples" / "launchers" / "dix_sway.toml"
HOT_ENTRY = REPOSITORY / "examples" / "launchers" / "dix_sway_navigation.py"


_FAKE_I3IPC = r'''
import json
import os
import re

_current = int(os.environ.get("DIX_TEST_INITIAL_FOCUS", "1"))
_live = [int(value) for value in os.environ.get("DIX_TEST_LIVE_IDS", str(_current)).split(",") if value]
_transitions = json.loads(os.environ.get("DIX_TEST_TRANSITIONS", "{}"))
_trace = os.environ.get("DIX_TEST_TRACE")

class _Reply:
    success = True
    error = None

class _Leaf:
    def __init__(self, con_id):
        self.id = con_id

class _Tree:
    def find_focused(self):
        return _Leaf(_current)
    def leaves(self):
        return [_Leaf(con_id) for con_id in _live]

class Connection:
    def get_tree(self):
        return _Tree()
    def command(self, command):
        global _current
        if _trace:
            with open(_trace, "a", encoding="utf-8") as handle:
                handle.write(command + "\n")
        if command.startswith("focus "):
            direction = command.split(" ", 1)[1]
            _current = int(_transitions.get(f"{_current}:{direction}", _current))
        else:
            match = re.fullmatch(r"\[con_id=(-?\d+)\] focus", command)
            if match is None:
                return [type("Reply", (), {"success": False, "error": "bad command"})()]
            _current = int(match.group(1))
        return [_Reply()]
'''


def _environment(home: Path, fake: Path, **overrides: str) -> dict[str, str]:
    inherited = {key: value for key, value in os.environ.items() if not key.startswith("ROBA_")}
    return {
        **inherited,
        "HOME": str(home),
        "PYTHONPATH": os.pathsep.join((str(fake), str(REPOSITORY / "src"))),
        "SWAYSOCK": "deterministic-navigation-socket",
        "DIX_SWAY_GROUP_STATE_FILE": str(home / "groups.json"),
        "DIX_SWAY_ACTIVE_MEMBERS_FILE": str(home / "active.txt"),
        **overrides,
    }


def _run(
    launcher: Path,
    environment: dict[str, str],
    *arguments: str,
    **overrides: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(launcher), *arguments],
        cwd=REPOSITORY,
        env={**environment, **overrides},
        text=True,
        capture_output=True,
        check=False,
    )


def _success(
    launcher: Path,
    environment: dict[str, str],
    *arguments: str,
    **overrides: str,
) -> subprocess.CompletedProcess[str]:
    completed = _run(launcher, environment, *arguments, **overrides)
    assert completed.returncode == 0, completed.stderr
    _assert_secret_free(completed)
    return completed


def _failure(
    launcher: Path,
    environment: dict[str, str],
    *arguments: str,
    **overrides: str,
) -> subprocess.CompletedProcess[str]:
    completed = _run(launcher, environment, *arguments, **overrides)
    assert completed.returncode != 0
    _assert_secret_free(completed)
    return completed


def _value(completed: subprocess.CompletedProcess[str]) -> object:
    return ast.literal_eval(completed.stdout.strip())


def _assert_secret_free(completed: subprocess.CompletedProcess[str]) -> None:
    output = f"{completed.stdout}\n{completed.stderr}"
    assert "control_token" not in output
    assert "owner_token" not in output


def _inject_context_state(home: Path, name: str, value: object) -> None:
    environment = {
        "ROBA_RUNTIME_ROOT": str(home / ".roba" / "runtime"),
        "ROBA_LOGS_ROOT": str(home / ".roba" / "logs"),
    }
    manager_path = principal_socket("default", "dix.control", "sway", environment)
    manager = RobaClient(env=environment, timeout=5.0).context(
        locator=f"unix:{manager_path}",
        scope="id:sway",
        token=None,
    )
    locator = manager.get("context_locator")
    token = manager.get("owner_token")
    assert isinstance(locator, str)
    assert isinstance(token, str)
    context = RobaClient(env=environment, timeout=5.0).context(
        locator=locator,
        token=token,
    )
    context.set(name, value)



def _context_state(home: Path) -> dict[str, object]:
    environment = {
        "ROBA_RUNTIME_ROOT": str(home / ".roba" / "runtime"),
        "ROBA_LOGS_ROOT": str(home / ".roba" / "logs"),
    }
    manager_path = principal_socket("default", "dix.control", "sway", environment)
    manager = RobaClient(env=environment, timeout=5.0).context(
        locator=f"unix:{manager_path}", scope="id:sway", token=None,
    )
    context = RobaClient(env=environment, timeout=5.0).context(
        locator=manager.get("context_locator"), token=manager.get("owner_token"),
    )
    return dict(context.state())

def test_state_routed_sway_navigation_across_launcher_processes(tmp_path: Path) -> None:
    launcher = build_launcher(SPEC, tmp_path / "dix_sway.py")
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "i3ipc.py").write_text(_FAKE_I3IPC, encoding="utf-8")
    home = Path(tempfile.mkdtemp(prefix="dix-sway-navigation-", dir="/tmp"))
    environment = _environment(home, fake)
    runtime_root = home / ".roba" / "runtime"
    running = False

    try:
        _failure(launcher, environment, "navigation", "current")
        _failure(
            launcher,
            environment,
            "group",
            "select",
            DIX_SWAY_GROUP_SELECT_GROUP="work",
            DIX_TEST_LIVE_IDS="1,3",
        )
        assert not runtime_root.exists()

        _success(launcher, environment, "runtime", "start")
        running = True
        assert _success(launcher, environment, "navigation", "current").stdout.strip() == "basic"

        for index, direction in enumerate(("left", "right", "up", "down"), start=1):
            trace = tmp_path / f"basic-{direction}.trace"
            result = _value(
                _success(
                    launcher,
                    environment,
                    "navigation",
                    direction,
                    DIX_TEST_INITIAL_FOCUS=str(index),
                    DIX_TEST_LIVE_IDS=f"{index},{index + 10}",
                    DIX_TEST_TRANSITIONS=json.dumps({f"{index}:{direction}": index + 10}),
                    DIX_TEST_TRACE=str(trace),
                )
            )
            assert result == {
                "direction": direction,
                "origin_id": index,
                "focused_id": index + 10,
                "changed": True,
            }
            assert trace.read_text(encoding="utf-8").splitlines() == [f"focus {direction}"]

        _success(launcher, environment, "group", "create", "--group", "work")
        for con_id in (1, 3, 99):
            _success(
                launcher,
                environment,
                "group",
                "add",
                "--group",
                "work",
                DIX_TEST_INITIAL_FOCUS=str(con_id),
            )
        selected_group = _success(
            launcher,
            environment,
            "group",
            "select",
            DIX_SWAY_GROUP_SELECT_GROUP="work",
            DIX_TEST_LIVE_IDS="1,3",
        )
        assert _value(selected_group) is True
        assert _success(launcher, environment, "group", "current").stdout.strip() == "work"
        private_state = json.loads(Path(environment["DIX_SWAY_GROUP_STATE_FILE"]).read_text())
        assert private_state == {"groups": {"work": [1, 3, 99]}, "active_group": "work"}
        assert Path(environment["DIX_SWAY_ACTIVE_MEMBERS_FILE"]).read_bytes() == b"1 3\n"
        coordination = _context_state(home)
        assert coordination["groups"] == ["work"]
        assert coordination["active_group"] == "work"
        assert "1" not in json.dumps({"groups": coordination["groups"], "active_group": coordination["active_group"]})

        Path(environment["DIX_SWAY_ACTIVE_MEMBERS_FILE"]).unlink()
        same_selection = _success(
            launcher, environment, "group", "select",
            DIX_SWAY_GROUP_SELECT_GROUP="work", DIX_TEST_LIVE_IDS="1,3",
        )
        assert _value(same_selection) is False
        assert Path(environment["DIX_SWAY_ACTIVE_MEMBERS_FILE"]).read_bytes() == b"1 3\n"

        hot = subprocess.run(
            [sys.executable, str(HOT_ENTRY), "right"], cwd=REPOSITORY,
            env={**environment, "DIX_TEST_INITIAL_FOCUS": "1", "DIX_TEST_LIVE_IDS": "1,2,3",
                 "DIX_TEST_TRANSITIONS": json.dumps({"1:right": 2, "2:right": 3})},
            text=True, capture_output=True, check=False,
        )
        assert hot.returncode == 0, hot.stderr
        assert json.loads(hot.stdout)["focused_id"] == 3

        projection = Path(environment["DIX_SWAY_ACTIVE_MEMBERS_FILE"])
        projection.write_bytes(b"1 99\n")
        stale_hot = subprocess.run(
            [sys.executable, str(HOT_ENTRY), "left"], cwd=REPOSITORY,
            env={**environment, "DIX_TEST_INITIAL_FOCUS": "1", "DIX_TEST_LIVE_IDS": "1,2",
                 "DIX_TEST_TRANSITIONS": json.dumps({"1:left": 2, "2:left": 2})},
            text=True, capture_output=True, check=False,
        )
        assert stale_hot.returncode == 0, stale_hot.stderr
        stale_result = json.loads(stale_hot.stdout)
        assert stale_result["stale_ids"] == [99]
        assert stale_result["focused_id"] == 1 and stale_result["restored"] is True
        projection.write_bytes(b"1 3\n")

        selected_navigation = _success(
            launcher,
            environment,
            "navigation",
            "select",
            DIX_SWAY_NAVIGATION_SELECT_NODE_SELECTOR="group",
        )
        assert _value(selected_navigation) is True
        assert _success(launcher, environment, "navigation", "current").stdout.strip() == "group"

        hit_trace = tmp_path / "group-hit.trace"
        hit = _value(
            _success(
                launcher,
                environment,
                "navigation",
                "right",
                DIX_TEST_INITIAL_FOCUS="1",
                DIX_TEST_LIVE_IDS="1,2,3",
                DIX_TEST_TRANSITIONS=json.dumps({"1:right": 2, "2:right": 3}),
                DIX_TEST_TRACE=str(hit_trace),
            )
        )
        assert hit == {
            "direction": "right",
            "origin_id": 1,
            "focused_id": 3,
            "matched": True,
            "restored": False,
            "visited_ids": [1, 2, 3],
            "stale_ids": [],
        }
        assert hit_trace.read_text(encoding="utf-8").splitlines() == [
            "focus right",
            "focus right",
        ]
        assert _value(_success(launcher, environment, "group", "show", "--group", "work")) == [
            1,
            3,
            99,
        ]

        restore_trace = tmp_path / "group-restore.trace"
        no_target = _value(
            _success(
                launcher,
                environment,
                "navigation",
                "left",
                DIX_TEST_INITIAL_FOCUS="1",
                DIX_TEST_LIVE_IDS="1,2,3",
                DIX_TEST_TRANSITIONS=json.dumps({"1:left": 2, "2:left": 2}),
                DIX_TEST_TRACE=str(restore_trace),
            )
        )
        assert no_target == {
            "direction": "left",
            "origin_id": 1,
            "focused_id": 1,
            "matched": False,
            "restored": True,
            "visited_ids": [1, 2],
            "stale_ids": [],
        }
        assert restore_trace.read_text(encoding="utf-8").splitlines() == [
            "focus left",
            "focus left",
            "[con_id=1] focus",
        ]

        rejected = _failure(
            launcher,
            environment,
            "navigation",
            "select",
            "--node_selector",
            "unknown",
        )
        assert "unknown Sway node selector" in rejected.stderr
        assert _success(launcher, environment, "navigation", "current").stdout.strip() == "group"

        _inject_context_state(home, "node_selector", "injected")
        routed = _failure(launcher, environment, "navigation", "right")
        assert "unknown Sway node selector" in routed.stderr

        _success(launcher, environment, "runtime", "stop")
        running = False
        _failure(launcher, environment, "navigation", "current")

        _success(launcher, environment, "runtime", "start")
        running = True
        assert _context_state(home) == {}
        assert _value(_success(launcher, environment, "group", "list")) == {"work": [1, 3, 99]}
        assert _context_state(home) == {}
        assert _success(launcher, environment, "group", "current").stdout.strip() == "work"
        assert _success(launcher, environment, "navigation", "current").stdout.strip() == "basic"
        _success(launcher, environment, "runtime", "stop")
        running = False
    finally:
        if running:
            _run(launcher, environment, "runtime", "stop")
        shutil.rmtree(home, ignore_errors=True)
