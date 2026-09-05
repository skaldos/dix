from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dix.assembly import CompositionAssemblyError, assemble_compositions
from dix.config import load_effective_config
from dix.server import create_app


def write_composition(module: Path, local_id: str, body: str, runtime: str) -> None:
    root = module / "compositions" / local_id
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(body)
    (root / "runtime.py").write_text(runtime)


def write_application(module: Path, local_id: str, body: str, runtime: str) -> None:
    root = module / "apps" / local_id
    root.mkdir(parents=True)
    (root / "app.toml").write_text(body)
    (root / "runtime.py").write_text(runtime)


def test_assembly_orders_cross_module_application_dependencies(tmp_path: Path) -> None:
    roots = tmp_path / "modules"
    write_composition(
        roots / "z-data",
        "data",
        '[composition]\nid = "data"\n',
        "class Runtime:\n    def __init__(self, *, context, config): pass\n",
    )
    write_application(
        roots / "m-base",
        "base",
        '[app]\nid = "base"\n',
        "class Runtime:\n    def __init__(self, *, context, config): pass\n",
    )
    write_application(
        roots / "a-root",
        "root",
        """\
[app]
id = "root"
[compositions.data]
use = "z-data/data"
[apps.base]
use = "m-base/base"
""",
        """\
class Runtime:
    def __init__(self, *, context, config, data, base): pass
""",
    )
    config_path = tmp_path / "dix.toml"
    config_path.write_text('[composition]\ntrusted_module_roots = ["modules"]\n')
    effective = load_effective_config(paths=[config_path], env={})

    assembly = assemble_compositions(effective.composition)

    assert [item.id for item in assembly.modules.module_descriptors()] == [
        "a-root",
        "m-base",
        "z-data",
    ]


def test_configured_startup_loads_dependencies_and_initializes_only_enabled_instances(
    tmp_path: Path,
) -> None:
    modules = tmp_path / "modules"
    log = tmp_path / "events"
    write_composition(
        modules / "z-base",
        "base",
        '[composition]\nid = "base"\n',
        (
            "from pathlib import Path\n"
            f"LOG = Path({str(log)!r})\n"
            "class Runtime:\n"
            "    def __init__(self, *, context, config): self.context = context\n"
            "    def init(self):\n"
            "        with LOG.open('a') as stream: stream.write('base.init\\n')\n"
            "    def cleanup(self):\n"
            "        with LOG.open('a') as stream: stream.write('base.cleanup\\n')\n"
        ),
    )
    write_composition(
        modules / "a-root",
        "root",
        """[composition]
id = "root"
[compositions.base]
use = "z-base/base"
""",
        (
            "from pathlib import Path\n"
            f"LOG = Path({str(log)!r})\n"
            "class Runtime:\n"
            "    def __init__(self, *, context, config, base): self.context = context\n"
            "    def init(self):\n"
            "        with LOG.open('a') as stream: stream.write('root.init\\n')\n"
            "    def cleanup(self):\n"
            "        with LOG.open('a') as stream: stream.write('root.cleanup\\n')\n"
        ),
    )
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "dix.toml"
    config_path.write_text(
        """[composition]
trusted_module_roots = ["../modules"]
[[composition.instance]]
id = "enabled"
use = "a-root/root"
startup = true
[[composition.instance]]
id = "disabled"
use = "a-root/root"
startup = false
"""
    )
    effective = load_effective_config(paths=[config_path], env={})

    app = create_app(effective)
    compositions = app.state.composition_component

    assert [item.inspection.id for item in app.state.module_component.modules()] == [
        "a-root",
        "z-base",
    ]
    assert [item.id for item in compositions.instances(scope_id="startup")] == [
        "enabled",
        "enabled/base",
    ]
    assert log.read_text().splitlines() == ["base.init", "root.init"]
    root = compositions.require_instance("startup", "enabled")
    child = compositions.require_instance("startup", "enabled/base")
    assert root.context.config_base_dir == config_dir.resolve()
    assert child.context.config_base_dir == (modules / "a-root" / "compositions" / "root").resolve()

    with TestClient(app):
        pass

    assert compositions.instances() == ()
    assert log.read_text().splitlines() == [
        "base.init",
        "root.init",
        "root.cleanup",
        "base.cleanup",
    ]
    app.state.composition_assembly.shutdown()


def test_invalid_trusted_graph_fails_before_any_candidate_import(tmp_path: Path) -> None:
    modules = tmp_path / "modules"
    marker = tmp_path / "imported"
    runtime = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).touch()\n"
        "class Runtime:\n"
        "    def __init__(self, *, context, config, dependency): pass\n"
    )
    write_composition(
        modules / "cycle",
        "first",
        """[composition]
id = "first"
[compositions.dependency]
use = "cycle/second"
""",
        runtime,
    )
    write_composition(
        modules / "cycle",
        "second",
        """[composition]
id = "second"
[compositions.dependency]
use = "cycle/first"
""",
        runtime,
    )
    config_path = tmp_path / "dix.toml"
    config_path.write_text('[composition]\ntrusted_module_roots = ["modules"]\n')
    effective = load_effective_config(paths=[config_path], env={})

    with pytest.raises(CompositionAssemblyError, match="dependency cycle"):
        assemble_compositions(effective.composition)

    assert marker.exists() is False
