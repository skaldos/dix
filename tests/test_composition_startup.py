from __future__ import annotations

from pathlib import Path

import pytest

from dix.assembly import CompositionAssemblyError, assemble_compositions
from dix.config import load_effective_config
from dix.server import create_app


def write_composition(module: Path, local_id: str, body: str, runtime: str) -> None:
    root = module / "compositions" / local_id
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(body)
    (root / "runtime.py").write_text(runtime)


def test_configured_startup_loads_dependencies_and_starts_only_enabled_instances(
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
            "    def start(self):\n"
            "        with LOG.open('a') as stream: stream.write('base.start\\n')\n"
            "    def stop(self):\n"
            "        with LOG.open('a') as stream: stream.write('base.stop\\n')\n"
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
            "    def start(self):\n"
            "        with LOG.open('a') as stream: stream.write('root.start\\n')\n"
            "    def stop(self):\n"
            "        with LOG.open('a') as stream: stream.write('root.stop\\n')\n"
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

    assert [item.inspection.id for item in compositions.modules()] == ["a-root", "z-base"]
    assert [item.id for item in compositions.instances(scope_id="startup")] == [
        "enabled",
        "enabled/base",
    ]
    assert log.read_text().splitlines() == ["base.start", "root.start"]
    root = compositions.require_instance("startup", "enabled")
    child = compositions.require_instance("startup", "enabled/base")
    assert root.context.config_base_dir == config_dir.resolve()
    assert child.context.config_base_dir == (
        modules / "a-root" / "compositions" / "root"
    ).resolve()


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
