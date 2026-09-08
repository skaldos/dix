from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path


def _run(*command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    workspace = Path(sys.argv[1]).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    repository = Path(__file__).resolve().parents[2]
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
    install_base = _run(
        str(base / "bin" / "pip"),
        "install",
        "--no-deps",
        str(wheel),
        cwd=repository,
    )
    if install_base.returncode != 0:
        sys.stderr.write(install_base.stderr)
        return install_base.returncode
    base_probe = _run(
        str(base / "bin" / "python"),
        "-c",
        "import importlib.util, dix; assert importlib.util.find_spec('typer') is None",
        cwd=workspace,
    )
    if base_probe.returncode != 0:
        sys.stderr.write(base_probe.stderr)
        return base_probe.returncode
    print("base-without-typer=ok")

    cli = workspace / "cli"
    subprocess.run([sys.executable, "-m", "venv", str(cli)], check=True)
    install_cli = _run(
        "uv",
        "pip",
        "install",
        "--python",
        str(cli / "bin" / "python"),
        f"{wheel}[cli]",
        cwd=repository,
    )
    if install_cli.returncode != 0:
        sys.stderr.write(install_cli.stderr)
        return install_cli.returncode

    module_path_result = _run(
        str(cli / "bin" / "python"),
        "-c",
        (
            "from dix.modules import first_party_module_path; "
            "print(first_party_module_path('dix/cli'))"
        ),
        cwd=workspace,
    )
    if module_path_result.returncode != 0:
        sys.stderr.write(module_path_result.stderr)
        return module_path_result.returncode
    cli_module = Path(module_path_result.stdout.strip())
    if not cli_module.is_dir():
        raise RuntimeError(f"installed CLI module is not a directory: {cli_module}")
    print("wheel-cli-module=ok")

    source_spec = repository / "examples" / "launchers" / "my_cli.toml"
    raw = tomllib.loads(source_spec.read_text())
    modules = raw["modules"]
    source_paths = {
        item["id"]: (source_spec.parent / item["source"]).resolve() for item in modules
    }
    generated_spec = workspace / "wheel-my-cli.toml"
    generated_spec.write_text(
        """\
[launcher]
name = "my_cli"
adapter = "python_cli"
application = "acme/my_cli/main"
function = "main"

[[modules]]
id = "dix/cli"
source = {cli_source!r}

[[modules]]
id = "acme/cli_base"
source = {base_source!r}

[[modules]]
id = "acme/cli_test"
source = {test_source!r}

[[modules]]
id = "acme/my_cli"
source = {assembly_source!r}
""".format(
            cli_source=str(cli_module),
            base_source=str(source_paths["acme/cli_base"]),
            test_source=str(source_paths["acme/cli_test"]),
            assembly_source=str(source_paths["acme/my_cli"]),
        )
    )
    launcher = workspace / "my_cli.py"
    generate = _run(
        str(cli / "bin" / "python"),
        "-m",
        "dix.bootstrap",
        "build",
        str(generated_spec),
        "--output",
        str(launcher),
        cwd=workspace,
    )
    if generate.returncode != 0:
        sys.stderr.write(generate.stderr)
        return generate.returncode
    execution = _run(
        str(cli / "bin" / "python"),
        str(launcher),
        "test",
        "hello",
        "--name",
        "Wheel",
        cwd=workspace,
    )
    sys.stdout.write(execution.stdout)
    sys.stderr.write(execution.stderr)
    return execution.returncode


if __name__ == "__main__":
    raise SystemExit(main())
