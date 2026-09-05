from __future__ import annotations

from pathlib import Path

from dix.core import CompositionComponent, ModuleComponent, create_core_component_registry
from dix.core.composition import CompositionInstanceSpec


def test_composition_lifecycle_remains_init_cleanup_only(tmp_path: Path) -> None:
    module = tmp_path / "module"
    root = module / "compositions" / "lifecycle"
    root.mkdir(parents=True)
    log = tmp_path / "events"
    (root / "composition.toml").write_text('[composition]\nid = "lifecycle"\n')
    (root / "runtime.py").write_text(
        "from pathlib import Path\n"
        f"LOG = Path({str(log)!r})\n"
        "class Runtime:\n"
        "    def __init__(self, *, context, config): pass\n"
        "    def init(self): LOG.write_text('init\\n')\n"
        "    def cleanup(self):\n"
        "        with LOG.open('a') as stream: stream.write('cleanup\\n')\n"
        "    def start(self): raise AssertionError('legacy hook must not run')\n"
        "    def stop(self): raise AssertionError('legacy hook must not run')\n"
    )
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    compositions = registry.require("composition", CompositionComponent)
    modules.load_module(module, module_id="acme/lifecycle")
    compositions.create_instance(
        CompositionInstanceSpec(
            "root",
            "acme/lifecycle/lifecycle",
            {},
            tmp_path,
        ),
        owner_scope_id="test",
    )

    compositions.initialize_instance("test", "root")
    compositions.cleanup_instance("test", "root")

    assert log.read_text().splitlines() == ["init", "cleanup"]
