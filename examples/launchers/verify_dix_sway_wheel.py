from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


EXPECTED_ROBA_COMMIT = "bdca5fbb4ba853657277dc87eeb28b6522e4270a"
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
            import os
            from types import SimpleNamespace

            class Connection:
                def get_tree(self):
                    focused = int(os.environ["DIX_TEST_FOCUS"])
                    return SimpleNamespace(find_focused=lambda: SimpleNamespace(id=focused))
            '''
        ),
        encoding="utf-8",
    )
    process_env = {
        **os.environ,
        "HOME": str(home),
        "PYTHONPATH": str(fake),
        "SWAYSOCK": "test-sway-socket",
        "DIX_TEST_FOCUS": "731",
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
        require_failure("group", "list")
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
        require_success("group", "add", "--group", "work")
        listed = require_success("group", "list")
        if listed.stdout.strip() != "{'work': [731]}":
            raise RuntimeError(f"unexpected launcher output: {listed.stdout!r}")

        require_success("runtime", "stop")
        runtime_running = False
        require_failure("runtime", "status")
        require_failure("group", "list")

        restarted = require_success("runtime", "start")
        runtime_running = True
        if "context_id" not in restarted.stdout or "sway" not in restarted.stdout:
            raise RuntimeError(f"runtime restart omitted Sway status: {restarted.stdout!r}")
        empty = require_success("group", "list")
        if empty.stdout.strip() != "{}":
            raise RuntimeError(f"restart restored stale group state: {empty.stdout!r}")
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
