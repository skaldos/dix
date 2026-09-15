from __future__ import annotations

import subprocess
import sys
import zipfile
from email.parser import BytesParser
from pathlib import Path

from dix.modules import first_party_module_path

REPOSITORY = Path(__file__).resolve().parents[1]


def test_roba_module_is_explicitly_resolvable_from_source() -> None:
    assert first_party_module_path("dix/roba") == (REPOSITORY / "modules" / "dix" / "roba").resolve()


def test_roba_wheel_contains_the_complete_first_party_module_and_optional_extra(tmp_path: Path) -> None:
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
        "dix/_modules/dix/roba/README.md",
        "dix/_modules/dix/roba/compositions/config/composition.toml",
        "dix/_modules/dix/roba/compositions/daemon/composition.toml",
        "dix/_modules/dix/roba/compositions/control/composition.toml",
        "dix/_modules/dix/roba/apps/daemon/app.toml",
        "dix/_modules/dix/roba/apps/control/app.toml",
        "dix/_modules/dix/roba/apps/managed/app.toml",
        "dix/_modules/dix/roba/apps/cli/app.toml",
    } <= names
    assert "roba" in metadata.get_all("Provides-Extra", [])
    requirements = metadata.get_all("Requires-Dist", [])
    for name in ("roba", "pydantic", "typer", "click"):
        assert any(item.startswith(name) and "extra == 'roba'" in item for item in requirements)


def test_wheel_installed_roba_module_runs_against_the_fixed_local_roba_wheel(tmp_path: Path) -> None:
    verify = REPOSITORY / "examples" / "launchers" / "verify_dix_roba_wheel.py"
    completed = subprocess.run(
        [sys.executable, str(verify), str(tmp_path / "verify")],
        cwd=REPOSITORY,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "wheel-roba-module=ok" in completed.stdout
