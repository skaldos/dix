from __future__ import annotations

import subprocess
import sys
import zipfile
from email.parser import BytesParser
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]


def test_wheel_contains_optional_first_party_cli_module(tmp_path: Path) -> None:
    output = tmp_path / "wheel"
    subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            "--no-sources",
            "--out-dir",
            str(output),
        ],
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
        "dix/_modules/dix/cli/README.md",
        "dix/_modules/dix/cli/compositions/typer/composition.toml",
        "dix/_modules/dix/cli/compositions/typer/runtime.py",
    } <= names
    assert not any(name.startswith("unstable/") for name in names)
    assert "cli" in metadata.get_all("Provides-Extra", [])
    typer_requirements = [
        item for item in metadata.get_all("Requires-Dist", []) if item.startswith("typer")
    ]
    assert len(typer_requirements) == 1
    assert "extra == 'cli'" in typer_requirements[0]


def test_base_project_metadata_has_no_required_runtime_dependency() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import dix; print(dix.__name__)"],
        cwd=REPOSITORY,
        check=True,
        text=True,
        capture_output=True,
    )
    assert result.stdout == "dix\n"
