from __future__ import annotations

import json
from pathlib import Path

from dix.cli import main


def test_help(capsys) -> None:
    try:
        main(["--help"])
    except SystemExit as e:
        assert e.code == 0
    out = capsys.readouterr().out
    assert "Declarative Interface eXecutor" in out


def test_config_effective_cli(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["config", "effective"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["values"]["port"] == 8000


def test_interface_new_and_list(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["interface", "new", "demo_request"]) == 0
    assert (tmp_path / "examples" / "interfaces" / "demo_request.toml").exists()
    capsys.readouterr()
    assert main(["interface", "list"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["id"] == "demo_request"


def test_component_list(capsys) -> None:
    assert main(["component", "list"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {row["id"] for row in rows} == {"input", "select"}
