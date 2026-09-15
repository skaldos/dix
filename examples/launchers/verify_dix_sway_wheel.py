from __future__ import annotations

import json
import ast
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


EXPECTED_ROBA_COMMIT = "afde02db17e5a85cb4e8bfebf31ecc6bac61c2a2"
REPOSITORY = Path(__file__).resolve().parents[2]
ROBA_REPOSITORY = Path(os.environ.get("DIX_ROBA_SOURCE", REPOSITORY.parent / "roba")).resolve()


def _run(
    *command: str,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _require(completed: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(completed.args)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_dix_sway_wheel.py OUTPUT_DIR")
    output = Path(sys.argv[1]).resolve()
    if output.exists():
        raise SystemExit(f"output path already exists: {output}")
    output.mkdir(parents=True)

    roba_head = _require(
        _run("git", "rev-parse", "HEAD", cwd=ROBA_REPOSITORY)
    ).stdout.strip()
    if roba_head != EXPECTED_ROBA_COMMIT:
        raise RuntimeError(f"unexpected ROBA commit: {roba_head}")

    roba_wheels = output / "roba-wheel"
    dix_wheels = output / "dix-wheel"
    roba_wheels.mkdir()
    dix_wheels.mkdir()
    _require(_run("uv", "build", "--wheel", "--out-dir", str(roba_wheels), cwd=ROBA_REPOSITORY))
    _require(
        _run(
            "uv",
            "build",
            "--wheel",
            "--no-sources",
            "--out-dir",
            str(dix_wheels),
            cwd=REPOSITORY,
        )
    )
    roba_wheel = next(roba_wheels.glob("roba-*.whl"))
    dix_wheel = next(dix_wheels.glob("dix-*.whl"))

    environment = output / "venv"
    _require(_run("uv", "venv", "--python", "3.12", str(environment), cwd=output))
    python = environment / "bin" / "python"
    requirements = output / "requirements.txt"
    requirements.write_text(
        f"roba @ {roba_wheel.as_uri()}\ndix[sway] @ {dix_wheel.as_uri()}\n",
        encoding="utf-8",
    )
    _require(
        _run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "-r",
            str(requirements),
            cwd=output,
        )
    )

    module_probe = _require(
        _run(
            str(python),
            "-c",
            (
                "import json; from dix.modules import first_party_module_path; "
                "print(json.dumps({key: str(first_party_module_path(key)) "
                "for key in ('dix/state', 'dix/cli', 'dix/roba', 'dix/sway')}))"
            ),
            cwd=output,
        )
    )
    module_paths = json.loads(module_probe.stdout)
    launcher_spec = output / "dix_sway.toml"
    launcher_spec.write_text(
        """\
[launcher]
name = "dix-sway"
adapter = "python_cli"
application = "dix/sway/cli"
function = "main"

[[modules]]
id = "dix/state"
source = {state!r}

[[modules]]
id = "dix/cli"
source = {cli!r}

[[modules]]
id = "dix/roba"
source = {roba!r}

[[modules]]
id = "dix/sway"
source = {sway!r}
""".format(
            state=module_paths["dix/state"],
            cli=module_paths["dix/cli"],
            roba=module_paths["dix/roba"],
            sway=module_paths["dix/sway"],
        ),
        encoding="utf-8",
    )
    launcher = output / "dix-sway.py"
    _require(
        _run(
            str(python),
            "-m",
            "dix.bootstrap",
            "build",
            str(launcher_spec),
            "--output",
            str(launcher),
            cwd=output,
        )
    )

    home = Path(tempfile.mkdtemp(prefix="dix-sway-wheel-", dir="/tmp"))
    runtime_root = home / ".roba" / "runtime"
    fake = output / "fake"
    fake.mkdir()
    (fake / "i3ipc.py").write_text(
        textwrap.dedent(
            '''\
            import json
            import os
            import re
            from types import SimpleNamespace

            _current = int(os.environ.get("DIX_TEST_INITIAL_FOCUS", "731"))
            _live = [
                int(value)
                for value in os.environ.get("DIX_TEST_LIVE_IDS", str(_current)).split(",")
                if value
            ]
            _transitions = json.loads(os.environ.get("DIX_TEST_TRANSITIONS", "{}"))

            class Connection:
                def get_tree(self):
                    return SimpleNamespace(
                        find_focused=lambda: SimpleNamespace(id=_current),
                        leaves=lambda: [SimpleNamespace(id=value) for value in _live],
                    )

                def command(self, command):
                    global _current
                    if command.startswith("focus "):
                        direction = command.split(" ", 1)[1]
                        _current = int(_transitions.get(f"{_current}:{direction}", _current))
                    else:
                        match = re.fullmatch(r"\\[con_id=(-?\\d+)\\] focus", command)
                        if match is None:
                            return [SimpleNamespace(success=False, error="bad command")]
                        _current = int(match.group(1))
                    return [SimpleNamespace(success=True, error=None)]
            '''
        ),
        encoding="utf-8",
    )
    process_env = {
        **os.environ,
        "HOME": str(home),
        "PYTHONPATH": str(fake),
        "SWAYSOCK": "test-sway-socket",
        "DIX_TEST_INITIAL_FOCUS": "731",
        "DIX_SWAY_GROUP_STATE_FILE": str(home / "groups.json"),
        "DIX_SWAY_ACTIVE_MEMBERS_FILE": str(home / "active.txt"),
    }
    runtime_running = False
    def run_launcher(*arguments: str) -> subprocess.CompletedProcess[str]:
        completed = _run(
            str(python),
            str(launcher),
            *arguments,
            cwd=output,
            env=process_env,
        )
        combined = f"{completed.stdout}\n{completed.stderr}"
        if "control_token" in combined or "owner_token" in combined:
            raise RuntimeError("installed Sway launcher exposed a ROBA credential")
        return completed

    def require_success(*arguments: str) -> subprocess.CompletedProcess[str]:
        completed = run_launcher(*arguments)
        if completed.returncode:
            raise RuntimeError(
                f"launcher failed ({completed.returncode}): {' '.join(arguments)}\n"
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        return completed

    def require_failure(*arguments: str) -> subprocess.CompletedProcess[str]:
        completed = run_launcher(*arguments)
        if completed.returncode == 0:
            raise RuntimeError(f"launcher unexpectedly succeeded: {' '.join(arguments)}")
        return completed

    try:
        require_failure("runtime", "status")
        pre_groups = require_success("group", "list")
        if pre_groups.stdout.strip() != "{}":
            raise RuntimeError("missing private group state was not empty")
        if runtime_root.exists():
            raise RuntimeError("pre-start inspection created a ROBA runtime root")

        started = require_success("runtime", "start")
        runtime_running = True
        if "context_id" not in started.stdout or "sway" not in started.stdout:
            raise RuntimeError(f"runtime start omitted Sway status: {started.stdout!r}")
        require_failure("runtime", "start")
        status = require_success("runtime", "status")
        if "context_ready" not in status.stdout:
            raise RuntimeError(f"runtime status omitted context readiness: {status.stdout!r}")

        require_success("group", "create", "--group", "work")
        for con_id in (1, 3, 99):
            process_env["DIX_TEST_INITIAL_FOCUS"] = str(con_id)
            require_success("group", "add", "--group", "work")
        listed = require_success("group", "list")
        if listed.stdout.strip() != "{'work': [1, 3, 99]}":
            raise RuntimeError(f"unexpected launcher output: {listed.stdout!r}")

        current = require_success("navigation", "current")
        if current.stdout.strip() != "basic":
            raise RuntimeError(f"unexpected default navigation: {current.stdout!r}")

        process_env.update(
            DIX_TEST_INITIAL_FOCUS="10",
            DIX_TEST_LIVE_IDS="10,20",
            DIX_TEST_TRANSITIONS=json.dumps({"10:right": 20}),
        )
        basic = ast.literal_eval(require_success("navigation", "right").stdout.strip())
        if basic != {
            "direction": "right",
            "origin_id": 10,
            "focused_id": 20,
            "changed": True,
        }:
            raise RuntimeError(f"unexpected basic navigation: {basic!r}")

        process_env["DIX_SWAY_GROUP_SELECT_GROUP"] = "work"
        process_env["DIX_TEST_LIVE_IDS"] = "1,3"
        require_success("group", "select")
        process_env["DIX_SWAY_NAVIGATION_SELECT_NODE_SELECTOR"] = "group"
        require_success("navigation", "select")
        process_env.pop("DIX_SWAY_GROUP_SELECT_GROUP")
        process_env.pop("DIX_SWAY_NAVIGATION_SELECT_NODE_SELECTOR")

        process_env.update(
            DIX_TEST_INITIAL_FOCUS="1",
            DIX_TEST_LIVE_IDS="1,2,3",
            DIX_TEST_TRANSITIONS=json.dumps({"1:right": 2, "2:right": 3}),
        )
        grouped = ast.literal_eval(require_success("navigation", "right").stdout.strip())
        if not grouped["matched"] or grouped["visited_ids"] != [1, 2, 3]:
            raise RuntimeError(f"unexpected group navigation: {grouped!r}")
        if grouped["stale_ids"] != []:
            raise RuntimeError(f"stale ID was not exposed: {grouped!r}")
        shown = ast.literal_eval(require_success("group", "show", "--group", "work").stdout.strip())
        if shown != [1, 3, 99]:
            raise RuntimeError(f"navigation mutated group state: {shown!r}")

        process_env.update(
            DIX_TEST_INITIAL_FOCUS="1",
            DIX_TEST_TRANSITIONS=json.dumps({"1:left": 2, "2:left": 2}),
        )
        restored = ast.literal_eval(require_success("navigation", "left").stdout.strip())
        if restored["matched"] or not restored["restored"] or restored["focused_id"] != 1:
            raise RuntimeError(f"unexpected no-target restore: {restored!r}")

        rejected = require_failure(
            "navigation", "select", "--node_selector", "unknown"
        )
        if "unknown Sway node selector" not in rejected.stderr:
            raise RuntimeError(f"unknown selector did not fail visibly: {rejected.stderr!r}")

        require_success("runtime", "stop")
        runtime_running = False
        require_failure("runtime", "status")
        post_groups = require_success("group", "list")
        if post_groups.stdout.strip() != "{'work': [1, 3, 99]}":
            raise RuntimeError("private group state was coupled to ROBA stop")

        restarted = require_success("runtime", "start")
        runtime_running = True
        if "context_id" not in restarted.stdout or "sway" not in restarted.stdout:
            raise RuntimeError(f"runtime restart omitted Sway status: {restarted.stdout!r}")
        empty = require_success("group", "list")
        if empty.stdout.strip() != "{'work': [1, 3, 99]}":
            raise RuntimeError(f"private group state did not survive ROBA restart: {empty.stdout!r}")
        if require_success("group", "current").stdout.strip() != "work":
            raise RuntimeError("private active group did not survive ROBA restart")
        if require_success("navigation", "current").stdout.strip() != "basic":
            raise RuntimeError("restart restored a non-default navigation selector")
        require_success("runtime", "stop")
        runtime_running = False
    finally:
        if runtime_running:
            run_launcher("runtime", "stop")
        shutil.rmtree(home, ignore_errors=True)

    print("wheel-sway-launcher=ok")
    print(f"dix-wheel={dix_wheel.name}")
    print(f"roba-wheel={roba_wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
