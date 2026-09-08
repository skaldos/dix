from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dix.bootstrap import build_launcher
from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec
from dix.modules import first_party_module_path

REPOSITORY = Path(__file__).resolve().parents[1]
EXAMPLES = REPOSITORY / "examples"
LAUNCHER_SPEC = EXAMPLES / "launchers" / "my_cli.toml"


def _build(tmp_path: Path) -> Path:
    return build_launcher(LAUNCHER_SPEC, tmp_path / "my_cli.py")


def _run(launcher: Path, *arguments: str, env: dict[str, str] | None = None):
    environment = {**os.environ, "PYTHONPATH": str(REPOSITORY / "src")}
    if env:
        environment.update(env)
    return subprocess.run(
        [sys.executable, str(launcher), *arguments],
        cwd=REPOSITORY,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_generated_cli_help_preserves_groups_commands_options_and_env(tmp_path: Path) -> None:
    launcher = _build(tmp_path)

    root = _run(launcher, "--help")
    assert root.returncode == 0
    assert "base" in root.stdout
    assert "test" in root.stdout

    base = _run(launcher, "base", "--help")
    assert base.returncode == 0
    assert "render" in base.stdout
    assert "status" in base.stdout

    command = _run(launcher, "base", "render", "--help")
    assert command.returncode == 0
    assert "Render one value repeatedly." in command.stdout
    assert "--value" in command.stdout
    assert "--count" in command.stdout
    assert "--upper" in command.stdout
    assert "MY_CLI_BASE_RENDER_VALUE" in command.stdout
    assert "hidden_helper" not in command.stdout

    test = _run(launcher, "test", "--help")
    assert test.returncode == 0
    assert "hello" in test.stdout
    assert "hello_world" in test.stdout
    assert "hello-world" not in test.stdout


def test_generated_cli_calls_sync_async_boolean_default_integer_and_env(tmp_path: Path) -> None:
    launcher = _build(tmp_path)

    upper = _run(
        launcher,
        "base",
        "render",
        "--value",
        "test",
        "--count",
        "2",
        "--upper",
        "true",
    )
    assert (upper.returncode, upper.stdout, upper.stderr) == (0, "TEST\nTEST\n", "")

    lower = _run(
        launcher,
        "base",
        "render",
        "--value",
        "test",
        "--upper",
        "false",
    )
    assert (lower.returncode, lower.stdout, lower.stderr) == (0, "test\n", "")

    hello = _run(launcher, "test", "hello", "--name", "Skaldos")
    assert (hello.returncode, hello.stdout, hello.stderr) == (0, "Hello Skaldos\n", "")

    asynchronous = _run(launcher, "test", "hello_world")
    assert (asynchronous.returncode, asynchronous.stdout, asynchronous.stderr) == (
        0,
        "Hello World\n",
        "",
    )

    environment = _run(
        launcher,
        "test",
        "hello",
        env={"MY_CLI_TEST_HELLO_NAME": "Environment"},
    )
    assert (environment.returncode, environment.stdout, environment.stderr) == (
        0,
        "Hello Environment\n",
        "",
    )


def test_manual_cli_application_owns_and_destroys_its_complete_graph(
    tmp_path: Path,
) -> None:
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    sources = (
        ("dix/cli", first_party_module_path("dix/cli")),
        ("acme/cli_base", EXAMPLES / "modules" / "acme" / "cli_base"),
        ("acme/cli_test", EXAMPLES / "modules" / "acme" / "cli_test"),
        ("acme/my_cli", EXAMPLES / "modules" / "acme" / "my_cli"),
    )
    for module_id, source in sources:
        modules.load_module(source, module_id=module_id)

    instance = applications.create_instance(
        ApplicationInstanceSpec("cli", "acme/my_cli/main", {}, tmp_path),
        owner_scope_id="e2e",
    )
    assert {(item.scope_id, item.id) for item in applications.instances()} == {
        ("e2e", "cli"),
        ("e2e", "cli/base"),
        ("e2e", "cli/test"),
    }
    assert instance.api.require("main")(["test", "status"]) == 0

    applications.destroy_instance("e2e", "cli")
    assert applications.instances() == ()
    for module_id, _ in reversed(sources):
        modules.unload_module(module_id)
    assert modules.module_descriptors() == ()
