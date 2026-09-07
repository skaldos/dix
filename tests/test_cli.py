from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    assert data["values"] == {"composition": {"instance": [], "trusted_module_roots": []}}


@pytest.mark.parametrize("command", ["serve", "interface", "component"])
def test_legacy_interface_commands_are_not_available(command: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main([command])
    assert exc_info.value.code == 2
