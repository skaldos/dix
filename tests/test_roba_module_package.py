from __future__ import annotations

from pathlib import Path

from dix.modules import first_party_module_path

REPOSITORY = Path(__file__).resolve().parents[1]


def test_roba_module_is_explicitly_resolvable_from_source() -> None:
    assert first_party_module_path("dix/roba") == (REPOSITORY / "modules" / "dix" / "roba").resolve()


def test_roba_config_module_has_no_daemon_or_application_surface_yet() -> None:
    root = first_party_module_path("dix/roba")
    assert (root / "compositions" / "config" / "composition.toml").is_file()
    assert not (root / "compositions" / "daemon").exists()
    assert not (root / "apps").exists()
