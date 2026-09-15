from __future__ import annotations

import importlib

import dix

PUBLIC_MODULES = (
    "dix.core",
    "dix.core.application",
    "dix.core.composition",
    "dix.core.module",
    "dix.bootstrap",
    "dix.modules",
)


def test_public_modules_export_existing_unique_names() -> None:
    for module_name in PUBLIC_MODULES:
        module = importlib.import_module(module_name)
        exports = module.__all__
        assert isinstance(exports, list)
        assert exports
        assert len(exports) == len(set(exports))
        assert all(isinstance(name, str) and name and hasattr(module, name) for name in exports)


def test_root_surface_stays_intentionally_small() -> None:
    assert dix.__version__ == "0.1.0"
    assert not hasattr(dix, "ApplicationComponent")
    assert not hasattr(dix, "build_launcher")
