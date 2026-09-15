from __future__ import annotations

import tomllib
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]


def test_public_alpha_metadata_is_explicit() -> None:
    with (REPOSITORY / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["name"] == "dix"
    assert project["version"] == "0.1.0"
    assert project["requires-python"] == ">=3.12"
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE"]
    assert project["urls"] == {
        "Homepage": "https://github.com/skaldos/dix",
        "Documentation": "https://dix.skaldos.dev",
        "Repository": "https://github.com/skaldos/dix",
        "Issues": "https://github.com/skaldos/dix/issues",
    }
    assert "Development Status :: 3 - Alpha" in project["classifiers"]
    assert "sway" not in project["optional-dependencies"]


def test_apache_license_is_materialized() -> None:
    license_text = (REPOSITORY / "LICENSE").read_text()
    assert license_text.startswith("Apache License\nVersion 2.0, January 2004")
    assert "http://www.apache.org/licenses/" in license_text
