from __future__ import annotations

import subprocess
import sys
import zipfile
from email.parser import BytesParser
from pathlib import Path

from dix.modules import first_party_module_path

REPOSITORY = Path(__file__).resolve().parents[1]
VERIFY = REPOSITORY / "examples" / "verify_config_wheel.py"


def test_config_module_is_explicitly_resolvable_from_source() -> None:
    source = first_party_module_path("dix/config")
    assert source == (REPOSITORY / "modules" / "dix" / "config").resolve()


def test_wheel_contains_optional_first_party_config_module(tmp_path: Path) -> None:
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
        "dix/_modules/dix/config/README.md",
        "dix/_modules/dix/config/compositions/pydantic/composition.toml",
        "dix/_modules/dix/config/compositions/pydantic/runtime.py",
    } <= names
    assert "config" in metadata.get_all("Provides-Extra", [])
    requirements = [
        item
        for item in metadata.get_all("Requires-Dist", [])
        if item.startswith("pydantic")
    ]
    assert len(requirements) == 1
    assert "extra == 'config'" in requirements[0]


def test_pydantic_is_not_a_base_runtime_dependency() -> None:
    assert subprocess.run(
        [
            "uv",
            "run",
            "--isolated",
            "--no-project",
            "--python",
            sys.executable,
            "--with",
            ".",
            "python",
            "-c",
            (
                "from importlib.metadata import requires; "
                "items = requires('dix') or []; "
                "assert not any(item.startswith('pydantic') and 'extra ==' not in item "
                "for item in items)"
            ),
        ],
        cwd=REPOSITORY,
        check=False,
    ).returncode == 0


def test_wheel_installed_config_module_resolves_a_model(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(VERIFY), str(tmp_path)],
        cwd=REPOSITORY,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "base-without-pydantic=ok" in completed.stdout
    assert "wheel-config-module=ok" in completed.stdout
