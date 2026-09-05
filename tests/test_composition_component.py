from __future__ import annotations

from pathlib import Path

import pytest

from dix.core import CompositionComponent, create_core_component_registry
from dix.core.composition import CompositionComponentError


def write_composition(
    module: Path,
    local_id: str,
    *,
    body: str | None = None,
    runtime: str = "class Runtime:\n    pass\n",
) -> Path:
    root = module / "compositions" / local_id
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(
        body or f'[composition]\nid = "{local_id}"\n'
    )
    (root / "runtime.py").write_text(runtime)
    return root


def component() -> CompositionComponent:
    registry = create_core_component_registry()
    return registry.require("composition", CompositionComponent)


def test_composition_component_is_runtime_scoped() -> None:
    registry = create_core_component_registry()

    first = registry.create_scope("first").require("composition", CompositionComponent)
    second = registry.create_scope("second").require("composition", CompositionComponent)

    assert second is first


def test_load_module_publishes_all_definitions_in_sorted_order(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    write_composition(module, "second")
    write_composition(module, "first")
    compositions = component()

    loaded = compositions.load_module(module, module_id="acme/bundle")

    assert tuple(loaded.compositions) == ("acme/bundle/first", "acme/bundle/second")
    assert [item.id for item in compositions.definitions()] == [
        "acme/bundle/first",
        "acme/bundle/second",
    ]
    assert [item.id for item in compositions.module_descriptors()] == ["acme/bundle"]
    assert compositions.require_module("acme/bundle") is loaded


def test_runtime_can_import_composition_local_python_modules(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    root = write_composition(
        module,
        "item",
        runtime="from .helper import VALUE\nclass Runtime:\n    value = VALUE\n",
    )
    (root / "helper.py").write_text("VALUE = 'local'\n")

    loaded = component().load_module(module, module_id="acme/bundle")

    assert loaded.compositions["acme/bundle/item"].runtime_type.value == "local"


def test_digest_mismatch_prevents_candidate_import(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    marker = tmp_path / "imported"
    write_composition(
        module,
        "item",
        runtime=f"from pathlib import Path\nPath({str(marker)!r}).touch()\nclass Runtime: pass\n",
    )
    compositions = component()

    with pytest.raises(CompositionComponentError, match="digest mismatch"):
        compositions.load_module(
            module,
            module_id="acme/bundle",
            expected_artifact_digest="0" * 64,
        )

    assert marker.exists() is False
    assert compositions.modules() == ()


def test_invalid_runtime_leaves_no_partial_registry_state(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    marker = tmp_path / "side-effect"
    write_composition(
        module,
        "first",
        runtime=f"from pathlib import Path\nPath({str(marker)!r}).touch()\nclass Runtime: pass\n",
    )
    write_composition(module, "second", runtime="class NotRuntime: pass\n")
    compositions = component()

    with pytest.raises(CompositionComponentError, match="runtime.py:Runtime"):
        compositions.load_module(module, module_id="acme/bundle")

    assert marker.exists() is True
    assert compositions.modules() == ()
    assert compositions.definitions() == ()


def test_load_does_not_execute_lifecycle_hooks(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    marker = tmp_path / "started"
    write_composition(
        module,
        "item",
        runtime=(
            "from pathlib import Path\n"
            "class Runtime:\n"
            "    def init(self):\n"
            f"        Path({str(marker)!r}).touch()\n"
        ),
    )

    component().load_module(module, module_id="acme/bundle")

    assert marker.exists() is False


@pytest.mark.parametrize("hook", ["init", "cleanup"])
def test_async_lifecycle_hook_is_rejected_during_load(
    tmp_path: Path,
    hook: str,
) -> None:
    module = tmp_path / "bundle"
    write_composition(
        module,
        "item",
        runtime=(
            "class Runtime:\n"
            "    def __init__(self, *, context, config): pass\n"
            f"    async def {hook}(self): pass\n"
        ),
    )

    with pytest.raises(
        CompositionComponentError,
        match=rf"async lifecycle hooks are not supported: acme/bundle/item\.{hook}",
    ):
        component().load_module(module, module_id="acme/bundle")


def test_duplicate_module_does_not_replace_loaded_state(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    write_composition(module, "item")
    compositions = component()
    loaded = compositions.load_module(module, module_id="acme/bundle")

    with pytest.raises(CompositionComponentError, match="already loaded"):
        compositions.load_module(module, module_id="acme/bundle")

    assert compositions.require_module("acme/bundle") is loaded


def test_unload_removes_an_instance_free_module(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    write_composition(module, "item")
    compositions = component()
    loaded = compositions.load_module(module, module_id="acme/bundle")

    assert compositions.unload_module("acme/bundle") is loaded
    assert compositions.modules() == ()
    assert compositions.definitions() == ()


def test_loaded_definition_dependency_blocks_unload(tmp_path: Path) -> None:
    base = tmp_path / "base"
    dependent = tmp_path / "dependent"
    write_composition(base, "item")
    write_composition(
        dependent,
        "child",
        body="""[composition]
id = "child"
[compositions.base]
use = "acme/base/item"
""",
    )
    compositions = component()
    base_loaded = compositions.load_module(base, module_id="acme/base")
    compositions.load_module(dependent, module_id="acme/dependent")

    with pytest.raises(CompositionComponentError, match="required by loaded composition"):
        compositions.unload_module("acme/base")

    assert compositions.require_module("acme/base") is base_loaded


def test_dependency_graph_contains_component_and_composition_edges(tmp_path: Path) -> None:
    base = tmp_path / "base"
    child = tmp_path / "child"
    write_composition(base, "item")
    write_composition(
        child,
        "item",
        body="""[composition]
id = "item"
[components]
model = "datamodel"
[compositions.base]
use = "acme/base/item"
""",
    )
    compositions = component()
    compositions.load_module(base, module_id="acme/base")
    compositions.load_module(child, module_id="acme/child")

    graph = compositions.describe_dependency_graph("acme/child/item")

    assert graph.nodes == ("acme/base/item", "acme/child/item")
    assert [(edge.kind, edge.alias, edge.target) for edge in graph.edges] == [
        ("component", "model", "datamodel"),
        ("composition", "base", "acme/base/item"),
    ]
