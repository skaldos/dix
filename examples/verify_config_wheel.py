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

    config = workspace / "config"
    subprocess.run([sys.executable, "-m", "venv", str(config)], check=True)
    config_install = _run(
        "uv",
        "pip",
        "install",
        "--python",
        str(config / "bin" / "python"),
        f"{wheel}[config]",
        cwd=workspace,
    )
    if config_install.returncode != 0:
        sys.stderr.write(config_install.stderr)
        return config_install.returncode

    probe = _run(
        str(config / "bin" / "python"),
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
            "m.load_module(first_party_module_path('dix/config'), module_id='dix/config'); "
            "i=c.create_instance(CompositionInstanceSpec('config','dix/config/pydantic',{},Path('.')), "
            "owner_scope_id='wheel'); "
            "model=i.api.require('resolve')({'name':'WheelConfig','fields':"
            "{'value':{'type':'string'}}}); "
            "assert model.model_validate({'value':'ok'}).value == 'ok'; "
            "print('wheel-config-module=ok')"
        ),
        cwd=workspace,
    )
    sys.stdout.write(probe.stdout)
    sys.stderr.write(probe.stderr)
    return probe.returncode


if __name__ == "__main__":
    raise SystemExit(main())
