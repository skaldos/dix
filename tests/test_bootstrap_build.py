from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dix.bootstrap import LauncherBuildError, build_launcher
from dix.core import ApplicationComponent, ModuleComponent
from dix.core.function import FunctionExecutionError

FIXTURE = Path(__file__).parent / "fixtures" / "bootstrap_seed"


def test_build_is_deterministic_and_requires_explicit_replace(tmp_path: Path) -> None:
    output = tmp_path / "launcher.py"
    build_launcher(FIXTURE / "launcher.toml", output)
    first = output.read_bytes()

    with pytest.raises(LauncherBuildError, match="already exists"):
        build_launcher(FIXTURE / "launcher.toml", output)
    assert output.read_bytes() == first

    build_launcher(FIXTURE / "launcher.toml", output, replace=True)
    assert output.read_bytes() == first
    assert not tuple(tmp_path.glob(".launcher.py.*.tmp"))


def test_failed_build_preserves_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "launcher.py"
    output.write_text("keep me")

    with pytest.raises(Exception, match="does not exist"):
        build_launcher(tmp_path / "missing.toml", output, replace=True)

    assert output.read_text() == "keep me"


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [([], "Hello World\n"), (["Skaldos"], "Hello Skaldos\n")],
)
def test_generated_launcher_runs_application(
    tmp_path: Path,
    arguments: list[str],
    expected: str,
) -> None:
    output = build_launcher(FIXTURE / "launcher.toml", tmp_path / "launcher.py")
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}

    completed = subprocess.run(
        [sys.executable, str(output), *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0
    assert completed.stdout == expected
    assert completed.stderr == ""


def test_generated_launcher_cleans_up_after_application_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = build_launcher(FIXTURE / "launcher.toml", tmp_path / "launcher.py")
    spec = importlib.util.spec_from_file_location("generated_cleanup_test", output)
    assert spec is not None and spec.loader is not None
    generated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generated)
    events: list[str] = []
    original_destroy = ApplicationComponent.destroy_instance
    original_unload = ModuleComponent.unload_module

    def destroy(self, scope_id, instance_id):
        events.append("destroy")
        return original_destroy(self, scope_id, instance_id)

    def unload(self, module_id):
        events.append(f"unload:{module_id}")
        return original_unload(self, module_id)

    monkeypatch.setattr(ApplicationComponent, "destroy_instance", destroy)
    monkeypatch.setattr(ModuleComponent, "unload_module", unload)

    with pytest.raises(FunctionExecutionError):
        generated._run(["fail"])

    assert events == ["destroy", "unload:acme/bootstrap_seed"]
