from __future__ import annotations

from pathlib import Path

from dix.core import CompositionComponent, create_core_component_registry
from dix.core.composition import CompositionInstanceSpec


def write_composition(module: Path, local_id: str, body: str, runtime: str) -> None:
    root = module / "compositions" / local_id
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(body)
    (root / "runtime.py").write_text(runtime)


def test_multi_composition_bundle_isolated_graphs_api_and_lifecycle(tmp_path: Path) -> None:
    module = tmp_path / "modules" / "pressure" / "bundle"
    log = tmp_path / "events"
    helper = (
        "from pathlib import Path\n"
        f"LOG = Path({str(log)!r})\n"
        "def record(value):\n"
        "    with LOG.open('a') as stream: stream.write(value + '\\n')\n"
    )
    write_composition(
        module,
        "base",
        """[composition]
id = "base"
[functions.echo]
description = "Echo."
[functions.label]
description = "Label."
""",
        helper
        + """class Runtime:
    def __init__(self, *, context, config): pass
    def echo(self, value: str) -> str: return value
    def label(self) -> str: return "base"
    def start(self): record("base.start")
    def stop(self): record("base.stop")
""",
    )
    write_composition(
        module,
        "child",
        """[composition]
id = "child"
[components]
model = "datamodel"
[compositions.base]
use = "pressure/bundle/base"
export = ["echo"]
[functions.base_label]
export = "base.label"
description = "Aliased label."
[functions.local]
description = "Local."
""",
        helper
        + """class Runtime:
    def __init__(self, *, context, config, model, base):
        self.model = model
        self.base = base
    def echo(self, value: str) -> str: return self.base.echo(value)
    def base_label(self) -> str: return self.base.label()
    def local(self) -> str: return "child"
    def start(self): record("child.start")
    def stop(self): record("child.stop")
""",
    )
    registry = create_core_component_registry()
    compositions = registry.require("composition", CompositionComponent)

    inspection = compositions.inspect_module(module, module_id="pressure/bundle")
    assert [item.local_id for item in inspection.definitions] == ["base", "child"]
    compositions.load_module(
        module,
        module_id="pressure/bundle",
        expected_artifact_digest=inspection.artifact_digest,
    )
    first = compositions.create_instance(
        CompositionInstanceSpec("first", "pressure/bundle/child", {}, tmp_path),
        owner_scope_id="pressure",
    )
    second = compositions.create_instance(
        CompositionInstanceSpec("second", "pressure/bundle/child", {}, tmp_path),
        owner_scope_id="pressure",
    )

    assert first.runtime is not second.runtime
    assert first.runtime.model is not second.runtime.model
    assert first.api.echo("value") == "value"
    assert first.api.base_label() == "base"
    assert first.api.local() == "child"
    assert compositions.describe_function("pressure/bundle/child", "echo").origin == "base.echo"
    assert compositions.describe_function(
        "pressure/bundle/child", "base_label"
    ).origin == "base.label"

    compositions.start_instance("pressure", "first")
    compositions.stop_instance("pressure", "first")
    assert log.read_text().splitlines() == [
        "base.start",
        "child.start",
        "child.stop",
        "base.stop",
    ]
