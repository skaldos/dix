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
    logs_root = home / ".roba" / "logs"
    process_env = {
        **os.environ,
        "HOME": str(home),
        "ROBA_RUNTIME_ROOT": str(runtime_root),
        "ROBA_LOGS_ROOT": str(logs_root),
    }
    setup = output / "setup.py"
    setup.write_text(
        textwrap.dedent(
            f'''\
            from pathlib import Path

            from roba import start_daemon
            from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
            from dix.core.application import ApplicationInstanceSpec
            from dix.modules import first_party_module_path

            environment = {{
                "ROBA_RUNTIME_ROOT": {str(runtime_root)!r},
                "ROBA_LOGS_ROOT": {str(logs_root)!r},
            }}
            creation = start_daemon("default", env=environment)
            registry = create_core_component_registry()
            modules = registry.require("module", ModuleComponent)
            applications = registry.require("application", ApplicationComponent)
            for module_id in ("dix/state", "dix/cli", "dix/roba"):
                modules.load_module(first_party_module_path(module_id), module_id=module_id)
            control = applications.create_instance(
                ApplicationInstanceSpec("control", "dix/roba/control", {{}}, Path.cwd()),
                owner_scope_id="wheel-setup",
            )
            control.api.require("bootstrap")(
                control_locator=str(creation.control_locator),
                control_token=creation.control_token,
                daemon_id="default",
                runtime_root={str(runtime_root)!r},
                logs_root={str(logs_root)!r},
                timeout=5.0,
            )
            control.api.require("create_context")(
                context_id="sway",
                daemon_id="default",
                runtime_root={str(runtime_root)!r},
                logs_root={str(logs_root)!r},
                timeout=5.0,
            )
            print("wheel-sway-runtime=ready")
            '''
        ),
        encoding="utf-8",
    )
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
    launcher_env = {
        **process_env,
        "PYTHONPATH": str(fake),
        "DIX_TEST_FOCUS": "731",
    }

    primary_error: BaseException | None = None
    try:
        setup_result = _require(_run(str(python), str(setup), cwd=output, env=process_env))
        if "wheel-sway-runtime=ready" not in setup_result.stdout:
            raise RuntimeError("wheel Sway setup did not report readiness")
        _require(
            _run(
                str(python),
                str(launcher),
                "group",
                "create",
                "--group",
                "work",
                cwd=output,
                env=launcher_env,
            )
        )
        _require(
            _run(
                str(python),
                str(launcher),
                "group",
                "add",
                "--group",
                "work",
                cwd=output,
                env=launcher_env,
            )
        )
        listed = _require(
            _run(
                str(python),
                str(launcher),
                "group",
                "list",
                cwd=output,
                env=launcher_env,
            )
        )
        if listed.stdout.strip() != "{'work': [731]}":
            raise RuntimeError(f"unexpected launcher output: {listed.stdout!r}")
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            stopped = _run(
                str(python),
                "-c",
                (
                    "from roba import stop_daemon; "
                    "stop_daemon(daemon='id:default', env={"
                    f"'ROBA_RUNTIME_ROOT': {str(runtime_root)!r}, "
                    f"'ROBA_LOGS_ROOT': {str(logs_root)!r}"
                    "})"
                ),
                cwd=output,
                env=process_env,
            )
            if stopped.returncode and primary_error is None:
                _require(stopped)
        finally:
            shutil.rmtree(home, ignore_errors=True)

    print("wheel-sway-launcher=ok")
    print(f"dix-wheel={dix_wheel.name}")
    print(f"roba-wheel={roba_wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
