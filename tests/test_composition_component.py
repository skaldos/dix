from __future__ import annotations

from pathlib import Path

import pytest

from dix.core import CompositionComponent, ModuleComponent, create_core_component_registry
from dix.core.composition import CompositionComponentError, CompositionInstanceSpec
from dix.core.module.component import ModuleComponentError


def write_composition(
    module: Path,
    local_id: str,
    *,
    body: str | None = None,
    runtime: str = ("class Runtime:\n    def __init__(self, *, context, config): pass\n"),
) -> Path:
    root = module / "compositions" / local_id
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(body or f'[composition]\nid = "{local_id}"\n')
    (root / "runtime.py").write_text(runtime)
    return root


def components() -> tuple[ModuleComponent, CompositionComponent]:
    registry = create_core_component_registry()
    return (
        registry.require("module", ModuleComponent),
        registry.require("composition", CompositionComponent),
    )


def test_composition_component_is_runtime_scoped() -> None:
    registry = create_core_component_registry()

    first = registry.create_scope("first").require("composition", CompositionComponent)
    second = registry.create_scope("second").require("composition", CompositionComponent)

    assert second is first


def test_load_module_publishes_all_definitions_in_sorted_order(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    write_composition(module, "second")
    write_composition(module, "first")
    modules, compositions = components()

    loaded = modules.load_module(module, module_id="acme/bundle")

    assert tuple(loaded.compositions) == ("acme/bundle/first", "acme/bundle/second")
    assert [item.id for item in compositions.definitions()] == [
        "acme/bundle/first",
        "acme/bundle/second",
    ]
    assert [item.id for item in modules.module_descriptors()] == ["acme/bundle"]
    assert modules.require_module("acme/bundle") is loaded


def test_runtime_can_import_composition_local_python_modules(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    root = write_composition(
        module,
        "item",
        runtime=(
            "from .helper import VALUE\n"
            "class Runtime:\n"
            "    value = VALUE\n"
            "    def __init__(self, *, context, config): pass\n"
        ),
    )
    (root / "helper.py").write_text("VALUE = 'local'\n")

    loaded = components()[0].load_module(module, module_id="acme/bundle")

    assert loaded.compositions["acme/bundle/item"].runtime_type.value == "local"


def test_digest_mismatch_prevents_candidate_import(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    marker = tmp_path / "imported"
    write_composition(
        module,
        "item",
        runtime=f"from pathlib import Path\nPath({str(marker)!r}).touch()\nclass Runtime: pass\n",
    )
    modules, _ = components()

    with pytest.raises(ModuleComponentError, match="digest mismatch"):
        modules.load_module(
            module,
            module_id="acme/bundle",
            expected_artifact_digest="0" * 64,
        )

    assert marker.exists() is False
    assert modules.modules() == ()


def test_invalid_runtime_leaves_no_partial_registry_state(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    marker = tmp_path / "side-effect"
    write_composition(
        module,
        "first",
        runtime=f"from pathlib import Path\nPath({str(marker)!r}).touch()\nclass Runtime: pass\n",
    )
    write_composition(module, "second", runtime="class NotRuntime: pass\n")
    modules, compositions = components()

    with pytest.raises(ModuleComponentError, match="runtime.py:Runtime"):
        modules.load_module(module, module_id="acme/bundle")

    assert marker.exists() is True
    assert modules.modules() == ()
    assert compositions.definitions() == ()


def test_load_does_not_execute_undeclared_runtime_methods(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    marker = tmp_path / "started"
    write_composition(
        module,
        "item",
        runtime=(
            "from pathlib import Path\n"
            "class Runtime:\n"
            "    def __init__(self, *, context, config): pass\n"
            "    def init(self):\n"
            f"        Path({str(marker)!r}).touch()\n"
        ),
    )

    components()[0].load_module(module, module_id="acme/bundle")

    assert marker.exists() is False


@pytest.mark.parametrize("function_id", ["init", "cleanup", "start", "stop"])
def test_previous_lifecycle_names_are_ordinary_declared_functions(
    tmp_path: Path,
    function_id: str,
) -> None:
    module = tmp_path / "bundle"
    marker = tmp_path / function_id
    root = module / "compositions" / "item"
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(
        f'[composition]\nid = "item"\n[functions.{function_id}]\n'
    )
    write_composition(
        module,
        "other",
        runtime="class Runtime:\n    def __init__(self, *, context, config): pass\n",
    )
    (root / "runtime.py").write_text(
            "class Runtime:\n"
            "    def __init__(self, *, context, config): pass\n"
            f"    def {function_id}(self):\n"
            f"        from pathlib import Path\n"
            f"        Path({str(marker)!r}).touch()\n"
    )
    modules, compositions = components()
    modules.load_module(module, module_id="acme/bundle")
    instance = compositions.create_instance(
        CompositionInstanceSpec("item", "acme/bundle/item", {}, tmp_path),
        owner_scope_id="test",
    )

    assert not marker.exists()
    instance.api.require(function_id)()
    assert marker.exists()
    assert not hasattr(compositions, "initialize_instance")
    assert not hasattr(compositions, "cleanup_instance")


def test_duplicate_module_does_not_replace_loaded_state(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    write_composition(module, "item")
    modules, _ = components()
    loaded = modules.load_module(module, module_id="acme/bundle")

    with pytest.raises(ModuleComponentError, match="already loaded"):
        modules.load_module(module, module_id="acme/bundle")

    assert modules.require_module("acme/bundle") is loaded


def test_unload_removes_an_instance_free_module(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    write_composition(module, "item")
    modules, compositions = components()
    loaded = modules.load_module(module, module_id="acme/bundle")

    assert modules.unload_module("acme/bundle") is loaded
    assert modules.modules() == ()
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
        runtime=("class Runtime:\n    def __init__(self, *, context, config, base): pass\n"),
    )
    modules, _ = components()
    base_loaded = modules.load_module(base, module_id="acme/base")
    modules.load_module(dependent, module_id="acme/dependent")

    with pytest.raises(CompositionComponentError, match="required by loaded composition"):
        modules.unload_module("acme/base")

    assert modules.require_module("acme/base") is base_loaded


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
        runtime=("class Runtime:\n    def __init__(self, *, context, config, model, base): pass\n"),
    )
    modules, compositions = components()
    modules.load_module(base, module_id="acme/base")
    modules.load_module(child, module_id="acme/child")

    graph = compositions.describe_dependency_graph("acme/child/item")

    assert graph.nodes == ("acme/base/item", "acme/child/item")
    assert [(edge.kind, edge.alias, edge.target) for edge in graph.edges] == [
        ("component", "model", "datamodel"),
        ("composition", "base", "acme/base/item"),
    ]
