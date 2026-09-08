from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(*command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def main() -> int:
    workspace = Path(sys.argv[1]).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    repository = Path(__file__).resolve().parents[1]
    wheel_dir = workspace / "wheel"
    build = _run(
        "uv",
        "build",
        "--wheel",
        "--no-sources",
        "--out-dir",
        str(wheel_dir),
        cwd=repository,
    )
    if build.returncode != 0:
        sys.stderr.write(build.stderr)
        return build.returncode
    wheel = next(wheel_dir.glob("*.whl"))

    base = workspace / "base"
    subprocess.run([sys.executable, "-m", "venv", str(base)], check=True)
    base_install = _run(
        str(base / "bin" / "pip"), "install", "--no-deps", str(wheel), cwd=workspace
    )
    if base_install.returncode != 0:
        sys.stderr.write(base_install.stderr)
        return base_install.returncode
    base_probe = _run(
        str(base / "bin" / "python"),
        "-c",
        "import importlib.util, dix; assert importlib.util.find_spec('pydantic') is None",
        cwd=workspace,
    )
    if base_probe.returncode != 0:
        sys.stderr.write(base_probe.stderr)
        return base_probe.returncode
    print("base-without-pydantic=ok")

    state = workspace / "state"
    subprocess.run([sys.executable, "-m", "venv", str(state)], check=True)
    state_install = _run(
        "uv",
        "pip",
        "install",
        "--python",
        str(state / "bin" / "python"),
        f"{wheel}[state]",
        cwd=workspace,
    )
    if state_install.returncode != 0:
        sys.stderr.write(state_install.stderr)
        return state_install.returncode

    probe = _run(
        str(state / "bin" / "python"),
        "-c",
        (
            "from dix.core import CompositionComponent, ModuleComponent, "
            "create_core_component_registry; "
            "from dix.core.composition import CompositionInstanceSpec; "
            "from dix.modules import first_party_module_path; "
            "from pathlib import Path; "
            "r=create_core_component_registry(); "
            "m=r.require('module', ModuleComponent); "
            "c=r.require('composition', CompositionComponent); "
            "m.load_module(first_party_module_path('dix/state'), module_id='dix/state'); "
            "i=c.create_instance(CompositionInstanceSpec('models','dix/state/models',{},Path('.')), "
            "owner_scope_id='wheel'); "
            "model=i.api.require('resolve')({'name':'WheelState','fields':"
            "{'value':{'type':'string'}}}); "
            "assert model.model_validate({'value':'ok'}).value == 'ok'; "
            "print('wheel-state-module=ok')"
        ),
        cwd=workspace,
    )
    sys.stdout.write(probe.stdout)
    sys.stderr.write(probe.stderr)
    if probe.returncode != 0:
        return probe.returncode

    pressure = _run(
        str(state / "bin" / "python"),
        str(repository / "examples" / "run_state_demo.py"),
        cwd=workspace,
    )
    sys.stderr.write(pressure.stderr)
    if pressure.returncode != 0:
        return pressure.returncode
    if '"reactions": 1' not in pressure.stdout:
        sys.stderr.write(pressure.stdout)
        return 1
    print("wheel-state-graph=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
