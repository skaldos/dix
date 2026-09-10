from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path


EXPECTED_ROBA_COMMIT = "bdca5fbb4ba853657277dc87eeb28b6522e4270a"
REPOSITORY = Path(__file__).resolve().parents[2]
ROBA_REPOSITORY = Path(os.environ.get("DIX_ROBA_SOURCE", REPOSITORY.parent / "roba")).resolve()


def _run(*command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def _require(completed: subprocess.CompletedProcess[str]) -> None:
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(completed.args)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_dix_roba_wheel.py OUTPUT_DIR")
    output = Path(sys.argv[1]).resolve()
    if output.exists():
        raise SystemExit(f"output path already exists: {output}")
    output.mkdir(parents=True)

    git_root = _run("git", "rev-parse", "--show-toplevel", cwd=ROBA_REPOSITORY)
    if git_root.returncode == 0 and Path(git_root.stdout.strip()).resolve() == ROBA_REPOSITORY:
        roba_head = _run("git", "rev-parse", "HEAD", cwd=ROBA_REPOSITORY).stdout.strip()
    else:
        roba_head = os.environ.get("DIX_ROBA_ARCHIVE_COMMIT", "")
    if roba_head != EXPECTED_ROBA_COMMIT:
        raise RuntimeError(f"unexpected ROBA commit: {roba_head}")

    roba_wheels = output / "roba-wheel"
    dix_wheels = output / "dix-wheel"
    roba_wheels.mkdir()
    dix_wheels.mkdir()
    _require(_run("uv", "build", "--wheel", "--out-dir", str(roba_wheels), cwd=ROBA_REPOSITORY))
    _require(_run("uv", "build", "--wheel", "--no-sources", "--out-dir", str(dix_wheels), cwd=REPOSITORY))
    roba_wheel = next(roba_wheels.glob("roba-*.whl"))
    dix_wheel = next(dix_wheels.glob("dix-*.whl"))

    environment = output / "venv"
    _require(_run("uv", "venv", "--python", "3.12", str(environment), cwd=output))
    python = environment / "bin" / "python"
    requirements = output / "requirements.txt"
    requirements.write_text(
        f"roba @ {roba_wheel.as_uri()}\ndix[roba] @ {dix_wheel.as_uri()}\n"
    )
    _require(_run("uv", "pip", "install", "--python", str(python), "-r", str(requirements), cwd=output))

    script = output / "wheel_execution.py"
    script.write_text(
        textwrap.dedent(
            '''\
            from pathlib import Path
            from tempfile import TemporaryDirectory

            import roba
            from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
            from dix.core.application import ApplicationInstanceSpec
            from dix.modules import first_party_module_path

            registry = create_core_component_registry()
            modules = registry.require("module", ModuleComponent)
            applications = registry.require("application", ApplicationComponent)
            for module_id in ("dix/state", "dix/cli", "dix/roba"):
                modules.load_module(first_party_module_path(module_id), module_id=module_id)
            with TemporaryDirectory(prefix="dix-roba-wheel-") as raw:
                root = Path(raw)
                cli = applications.create_instance(
                    ApplicationInstanceSpec("cli", "dix/roba/cli", {}, root),
                    owner_scope_id="wheel-cli",
                )
                assert [item.id for item in cli.api.functions()] == ["main"]
                config = {
                    "daemon_id": "wheel",
                    "runtime_root": str(root / "runtime"),
                    "logs_root": str(root / "logs"),
                    "timeout": 5.0,
                }
                app = applications.create_instance(
                    ApplicationInstanceSpec("daemon", "dix/roba/daemon", {}, root),
                    owner_scope_id="wheel",
                )
                app.api.require("start")(**config)
                assert app.api.require("status")(**config)["daemon_id"] == "wheel"
                app.api.require("stop")(**config)
                managed = applications.create_instance(
                    ApplicationInstanceSpec("managed", "dix/roba/managed", {}, root),
                    owner_scope_id="wheel",
                )
                managed_result = managed.api.require("start")(**config)
                assert managed_result["control_context"] == "dix.control"
                roba.stop_daemon(
                    daemon="id:wheel",
                    env={
                        "ROBA_RUNTIME_ROOT": str(root / "runtime"),
                        "ROBA_LOGS_ROOT": str(root / "logs"),
                    },
                )
            print(f"roba-version={roba.__version__}")
            print("wheel-roba-module=ok")
            '''
        )
    )
    executed = _run(str(python), str(script), cwd=output)
    _require(executed)
    assert "wheel-roba-module=ok" in executed.stdout
    print("wheel-roba-module=ok")
    print(f"roba-wheel={roba_wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
