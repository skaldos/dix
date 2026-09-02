from __future__ import annotations

from pathlib import Path

from dix.config import load_effective_config, write_default_config


def test_effective_config_uses_defaults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DIX_PORT", raising=False)
    cfg = load_effective_config(cwd=tmp_path, paths=[], env={})
    assert cfg.values["port"] == 8000
    assert cfg.sources["port"].source == "default"


def test_effective_config_file_and_env_sources(tmp_path: Path) -> None:
    config_path = tmp_path / "dix.toml"
    config_path.write_text('port = 9000\ntheme = \"file-theme\"\n')
    cfg = load_effective_config(paths=[config_path], env={"DIX_PORT": "9001"})
    assert cfg.values["port"] == 9001
    assert cfg.sources["port"].source == "env"
    assert cfg.values["theme"] == "file-theme"
    assert cfg.sources["theme"].source == "file"


def test_write_default_config(tmp_path: Path) -> None:
    path = tmp_path / "dix.toml"
    assert write_default_config(path) is True
    assert write_default_config(path) is False
    assert "runtime_root" in path.read_text()
