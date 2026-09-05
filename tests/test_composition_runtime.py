from __future__ import annotations

from pathlib import Path

import pytest

from dix.core import (
    CompositionComponent,
    DatamodelComponent,
    ModuleComponent,
    create_core_component_registry,
)
from dix.core.composition import (
    CompositionComponentError,
    CompositionInstanceSpec,
)
from dix.core.module.component import ModuleComponentError


def write_composition(module: Path, local_id: str, body: str, runtime: str) -> Path:
    root = module / "compositions" / local_id
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(body)
    (root / "runtime.py").write_text(runtime)
    return root


def runtime_components() -> tuple[ModuleComponent, CompositionComponent]:
    registry = create_core_component_registry()
    return (
        registry.require("module", ModuleComponent),
        registry.require("composition", CompositionComponent),
    )


def write_base_and_child(module: Path) -> None:
    write_composition(
        module,
        "base",
        """[composition]
id = "base"
[components]
datamodel = "datamodel"
[functions.echo]
description = "Echo a value."
""",
        """class Runtime:
    def __init__(self, *, context, config, datamodel):
        self.context = context
        self.config = config
        self.datamodel = datamodel

    def echo(self, value: str, *, loud: bool = False) -> str:
        return value.upper() if loud else value

    def hidden(self):
        return "not exported"
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
use = "test/runtime/base"
export = ["echo"]
config = { child_value = "configured" }
[functions.echo_alias]
export = "base.echo"
description = "Alias echo."
[functions.local_value]
description = "Return local state."
""",
        """class Runtime:
    def __init__(self, *, context, config, model, base):
        self.context = context
        self.config = config
        self.model = model
        self.base = base

    def echo(self, value: str, *, loud: bool = False) -> str:
        return self.base.echo(value, loud=loud)

    def echo_alias(self, value: str) -> str:
        return self.base.echo(value)

    def local_value(self) -> str:
        return "local"

    def hidden(self) -> str:
        return "not declared"
""",
    )


def create_child(
    modules: ModuleComponent,
    compositions: CompositionComponent,
    module: Path,
    *,
    instance_id: str = "request",
    owner: str = "test",
    config_base_dir: Path,
):
    modules.load_module(module, module_id="test/runtime")
    return compositions.create_instance(
        CompositionInstanceSpec(
            id=instance_id,
            use="test/runtime/child",
            config={"root_value": "configured"},
            config_base_dir=config_base_dir,
        ),
        owner_scope_id=owner,
    )


def test_parent_child_component_graph_and_declared_api(tmp_path: Path) -> None:
    module = tmp_path / "module"
    write_base_and_child(module)
    modules, compositions = runtime_components()

    root = create_child(modules, compositions, module, config_base_dir=tmp_path / "config")
    child = compositions.require_instance("test", "request/base")

    assert root.api.echo("hello", loud=True) == "HELLO"
    assert root.api.echo_alias("hello") == "hello"
    assert root.api.local_value() == "local"
    with pytest.raises(AttributeError):
        _ = root.api.hidden
    assert root.context.instance_id == "request"
    assert root.context.composition_id == "test/runtime/child"
    assert root.context.module_id == "test/runtime"
    assert root.context.module_root == module.resolve()
    assert root.context.composition_root == (module / "compositions" / "child").resolve()
    assert root.context.config_base_dir == (tmp_path / "config").resolve()
    assert root.context.owner_scope_id == "test"
    assert child.context.config_base_dir == root.context.composition_root
    assert child.runtime.config == {"child_value": "configured"}
    assert root.runtime.model is not child.runtime.datamodel


def test_function_descriptors_use_local_signature_and_wrapper_origin(tmp_path: Path) -> None:
    module = tmp_path / "module"
    write_base_and_child(module)
    modules, compositions = runtime_components()
    create_child(modules, compositions, module, config_base_dir=tmp_path)

    descriptor = compositions.describe_function("test/runtime/child", "echo")
    alias = compositions.describe_function("test/runtime/child", "echo_alias")
    local = compositions.describe_function("test/runtime/child", "local_value")

    assert descriptor.source == "local_wrapper"
    assert descriptor.origin == "base.echo"
    assert str(descriptor.signature) == "(value: str, *, loud: bool = False) -> str"
    assert descriptor.return_annotation is str
    assert alias.origin == "base.echo"
    assert str(alias.signature) == "(value: str) -> str"
    assert local.source == "local"
    assert local.origin is None
    assert [
        item.id for item in compositions.describe_composition("test/runtime/child").functions
    ] == [
        "echo",
        "echo_alias",
        "local_value",
    ]


def test_two_root_graphs_are_fully_isolated(tmp_path: Path) -> None:
    module = tmp_path / "module"
    write_base_and_child(module)
    modules, compositions = runtime_components()
    modules.load_module(module, module_id="test/runtime")

    first = compositions.create_instance(
        CompositionInstanceSpec("first", "test/runtime/child", {}, tmp_path),
        owner_scope_id="owner",
    )
    second = compositions.create_instance(
        CompositionInstanceSpec("second", "test/runtime/child", {}, tmp_path),
        owner_scope_id="owner",
    )
    first_child = compositions.require_instance("owner", "first/base")
    second_child = compositions.require_instance("owner", "second/base")

    assert first.runtime is not second.runtime
    assert first_child.runtime is not second_child.runtime
    assert first.runtime.model is not second.runtime.model
    assert first_child.runtime.datamodel is not second_child.runtime.datamodel


def test_same_definition_under_two_aliases_creates_two_children(tmp_path: Path) -> None:
    module = tmp_path / "module"
    write_base_and_child(module)
    write_composition(
        module,
        "double",
        """[composition]
id = "double"
[compositions.first]
use = "test/runtime/base"
[compositions.second]
use = "test/runtime/base"
""",
        """class Runtime:
    def __init__(self, *, context, config, first, second):
        self.first = first
        self.second = second
""",
    )
    modules, compositions = runtime_components()
    modules.load_module(module, module_id="test/runtime")

    compositions.create_instance(
        CompositionInstanceSpec("double", "test/runtime/double", {}, tmp_path),
        owner_scope_id="owner",
    )

    first = compositions.require_instance("owner", "double/first")
    second = compositions.require_instance("owner", "double/second")
    assert first.runtime is not second.runtime
    assert first.runtime.datamodel is not second.runtime.datamodel


def test_component_aliases_share_one_instance_inside_node(tmp_path: Path) -> None:
    module = tmp_path / "module"
    write_composition(
        module,
        "aliases",
        """[composition]
id = "aliases"
[components]
first = "datamodel"
second = "datamodel"
""",
        """class Runtime:
    def __init__(self, *, context, config, first, second):
        self.first = first
        self.second = second
""",
    )
    modules, compositions = runtime_components()
    modules.load_module(module, module_id="test/runtime")
    root = compositions.create_instance(
        CompositionInstanceSpec("aliases", "test/runtime/aliases", {}, tmp_path),
        owner_scope_id="owner",
    )

    assert isinstance(root.runtime.first, DatamodelComponent)
    assert root.runtime.first is root.runtime.second


def test_keyword_only_constructor_dependency_order_is_not_semantic(tmp_path: Path) -> None:
    module = tmp_path / "module"
    write_composition(
        module,
        "ordered",
        """[composition]
id = "ordered"
[components]
first = "datamodel"
second = "element"
""",
        """class Runtime:
    def __init__(self, *, second, config, first, context):
        self.first = first
        self.second = second
""",
    )
    modules, compositions = runtime_components()
    modules.load_module(module, module_id="test/runtime")

    root = compositions.create_instance(
        CompositionInstanceSpec("ordered", "test/runtime/ordered", {}, tmp_path),
        owner_scope_id="owner",
    )

    assert root.runtime.first.component_id == "datamodel"
    assert root.runtime.second.component_id == "element"


def test_dependency_cycle_fails_before_runtime_construction(tmp_path: Path) -> None:
    module = tmp_path / "module"
    marker = tmp_path / "constructed"
    runtime = (
        "from pathlib import Path\n"
        "class Runtime:\n"
        "    def __init__(self, *, context, config, dependency):\n"
        f"        Path({str(marker)!r}).touch()\n"
    )
    write_composition(
        module,
        "first",
        """[composition]
id = "first"
[compositions.dependency]
use = "test/runtime/second"
""",
        runtime,
    )
    write_composition(
        module,
        "second",
        """[composition]
id = "second"
[compositions.dependency]
use = "test/runtime/first"
""",
        runtime,
    )
    with pytest.raises(ModuleComponentError, match="dependency cycle"):
        modules, compositions = runtime_components()
        modules.load_module(module, module_id="test/runtime")

    assert marker.exists() is False
    assert compositions.instances() == ()


def test_missing_dependency_function_fails_before_runtime_construction(tmp_path: Path) -> None:
    module = tmp_path / "module"
    marker = tmp_path / "constructed"
    write_composition(
        module,
        "base",
        '[composition]\nid = "base"\n',
        "class Runtime:\n    def __init__(self, *, context, config): pass\n",
    )
    write_composition(
        module,
        "child",
        """[composition]
id = "child"
[compositions.base]
use = "test/runtime/base"
export = ["missing"]
""",
        (
            "from pathlib import Path\n"
            "class Runtime:\n"
            "    def __init__(self, *, context, config, base):\n"
            f"        Path({str(marker)!r}).touch()\n"
            "    def missing(self): return self.base.missing()\n"
        ),
    )
    with pytest.raises(ModuleComponentError, match="undeclared function"):
        modules, compositions = runtime_components()
        modules.load_module(module, module_id="test/runtime")

    assert marker.exists() is False
    assert compositions.instances() == ()


def test_unknown_component_and_composition_fail_before_instances_are_visible(
    tmp_path: Path,
) -> None:
    component_module = tmp_path / "component"
    write_composition(
        component_module,
        "broken",
        """[composition]
id = "broken"
[components]
missing = "unknown"
""",
        "class Runtime:\n    def __init__(self, *, context, config, missing): pass\n",
    )
    with pytest.raises(ModuleComponentError, match="component provider not found"):
        modules, compositions = runtime_components()
        modules.load_module(component_module, module_id="test/component")

    dependency_module = tmp_path / "dependency"
    write_composition(
        dependency_module,
        "broken",
        """[composition]
id = "broken"
[compositions.missing]
use = "test/absent/item"
""",
        "class Runtime:\n    def __init__(self, *, context, config, missing): pass\n",
    )
    with pytest.raises(ModuleComponentError, match="definition is not loaded"):
        modules.load_module(dependency_module, module_id="test/dependency")

    assert compositions.instances() == ()


@pytest.mark.parametrize(
    ("runtime", "message"),
    [
        (
            "class Runtime:\n    def __init__(self, *, context, config, extra): pass\n",
            "constructor",
        ),
        (
            "class Runtime:\n    def __init__(self, *, context, config): pass\n",
            "wrapper method",
        ),
    ],
)
def test_invalid_runtime_contract_leaves_no_partial_graph(
    tmp_path: Path,
    runtime: str,
    message: str,
) -> None:
    module = tmp_path / "module"
    body = """[composition]
id = "broken"
[functions.work]
description = "Work."
"""
    write_composition(module, "broken", body, runtime)
    with pytest.raises(ModuleComponentError, match=message):
        modules, compositions = runtime_components()
        modules.load_module(module, module_id="test/runtime")

    assert compositions.instances() == ()


def test_destroy_removes_complete_inactive_graph(tmp_path: Path) -> None:
    module = tmp_path / "module"
    write_base_and_child(module)
    modules, compositions = runtime_components()
    create_child(modules, compositions, module, config_base_dir=tmp_path)

    compositions.destroy_instance("test", "request")

    assert compositions.instances(scope_id="test") == ()
    with pytest.raises(CompositionComponentError, match="not found"):
        compositions.require_instance("test", "request/base")


def test_external_root_graph_blocks_dependency_module_unload(tmp_path: Path) -> None:
    base_module = tmp_path / "base"
    root_module = tmp_path / "root"
    write_composition(
        base_module,
        "base",
        """[composition]
id = "base"
[functions.echo]
description = "Echo."
""",
        """class Runtime:
    def __init__(self, *, context, config): pass
    def echo(self, value): return value
""",
    )
    write_composition(
        root_module,
        "root",
        """[composition]
id = "root"
[compositions.base]
use = "test/base/base"
""",
        "class Runtime:\n    def __init__(self, *, context, config, base): pass\n",
    )
    modules, compositions = runtime_components()
    modules.load_module(base_module, module_id="test/base")
    modules.load_module(root_module, module_id="test/root")
    compositions.create_instance(
        CompositionInstanceSpec("root", "test/root/root", {}, tmp_path),
        owner_scope_id="owner",
    )

    with pytest.raises(ModuleComponentError, match="loaded composition definition"):
        modules.unload_module("test/base")

    assert len(compositions.instances()) == 2
