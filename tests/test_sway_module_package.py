from __future__ import annotations

import subprocess
import zipfile
from email.parser import BytesParser
from pathlib import Path

from dix.bootstrap import build_launcher
from dix.modules import first_party_module_path


REPOSITORY = Path(__file__).resolve().parents[1]
SPEC = REPOSITORY / "examples" / "launchers" / "dix_sway.toml"
VERIFY = REPOSITORY / "examples" / "launchers" / "verify_dix_sway_wheel.py"


def test_sway_module_is_resolvable_and_launcher_spec_builds(tmp_path: Path) -> None:
    assert first_party_module_path("dix/sway") == (REPOSITORY / "modules/dix/sway").resolve()
    launcher = build_launcher(SPEC, tmp_path / "dix_sway.py")
    assert launcher.is_file()
    assert "dix/sway/cli" in launcher.read_text(encoding="utf-8")


def test_sway_wheel_contains_module_and_optional_dependency_only(tmp_path: Path) -> None:
    output = tmp_path / "wheel"
    subprocess.run(
        ["uv", "build", "--wheel", "--no-sources", "--out-dir", str(output)],
        cwd=REPOSITORY,
        check=True,
        text=True,
        capture_output=True,
    )
    wheel = next(output.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
    assert {
        "dix/_modules/dix/sway/README.md",
        "dix/_modules/dix/sway/compositions/ipc/composition.toml",
        "dix/_modules/dix/sway/compositions/ipc/runtime.py",
        "dix/_modules/dix/sway/compositions/groups/composition.toml",
        "dix/_modules/dix/sway/apps/groups/app.toml",
        "dix/_modules/dix/sway/apps/runtime/app.toml",
        "dix/_modules/dix/sway/apps/runtime/runtime.py",
        "dix/_modules/dix/sway/apps/cli/app.toml",
    } <= names
    assert "sway" in metadata.get_all("Provides-Extra", [])
    requirements = metadata.get_all("Requires-Dist", [])
    assert any(item.startswith("i3ipc==2.2.1") and "extra == 'sway'" in item for item in requirements)
    assert all("; extra ==" in item for item in requirements)


def test_installed_wheel_builds_and_executes_sway_launcher(tmp_path: Path) -> None:
    completed = subprocess.run(
        ["uv", "run", "--extra", "sway", "python", str(VERIFY), str(tmp_path / "verify")],
        cwd=REPOSITORY,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "wheel-sway-launcher=ok" in completed.stdout
