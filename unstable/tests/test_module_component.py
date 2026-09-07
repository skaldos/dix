from __future__ import annotations

from pathlib import Path

import pytest

from dix.core import (
    ApplicationComponent,
    CompositionComponent,
    ModuleComponent,
    create_core_component_registry,
)
from dix.core.application import ApplicationInstanceSpec
from dix.core.composition import CompositionInstanceSpec
from dix.core.module.component import ModuleComponentError

COMPOSITION_RUNTIME = """\
class Runtime:
    def __init__(self, *, context, config):
        self.context = context
"""

APPLICATION_RUNTIME = """\
class Runtime:
    def __init__(self, *, context, config):
        self.context = context
"""


def write_composition(
    module: Path,
    local_id: str,
    *,
    spec: str | None = None,
    runtime: str = COMPOSITION_RUNTIME,
) -> None:
    root = module / "compositions" / local_id
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(spec or f'[composition]\nid = "{local_id}"\n')
    (root / "runtime.py").write_text(runtime)


def write_application(
    module: Path,
    local_id: str,
    *,
    spec: str | None = None,
    runtime: str = APPLICATION_RUNTIME,
) -> None:
    root = module / "apps" / local_id
    root.mkdir(parents=True)
    (root / "app.toml").write_text(spec or f'[app]\nid = "{local_id}"\n')
    (root / "runtime.py").write_text(runtime)


def runtime_components():
    registry = create_core_component_registry()
    return (
        registry.require("module", ModuleComponent),
        registry.require("composition", CompositionComponent),
        registry.require("application", ApplicationComponent),
    )


def test_module_component_is_runtime_scoped_and_is_the_only_module_registry() -> None:
    registry = create_core_component_registry()

    first = registry.create_scope("first").require("module", ModuleComponent)
    second = registry.create_scope("second").require("module", ModuleComponent)
    compositions = registry.require("composition", CompositionComponent)

    assert first is second
    assert not hasattr(compositions, "load_module")
    assert not hasattr(compositions, "modules")


def test_mixed_module_is_published_as_one_registry_unit(tmp_path: Path) -> None:
    module = tmp_path / "mixed"
    write_composition(module, "data")
    write_application(
        module,
        "tool",
        spec="""\
[app]
id = "tool"
[compositions.data]
use = "acme/mixed/data"
""",
        runtime="""\
class Runtime:
    def __init__(self, *, context, config, data):
        self.context = context
""",
    )
    modules, compositions, applications = runtime_components()

    loaded = modules.load_module(module, module_id="acme/mixed")

    assert tuple(loaded.compositions) == ("acme/mixed/data",)
    assert tuple(loaded.applications) == ("acme/mixed/tool",)
    assert [item.id for item in compositions.definitions()] == ["acme/mixed/data"]
    assert [item.id for item in applications.definitions()] == ["acme/mixed/tool"]
    assert modules.module_descriptors()[0].composition_ids == ("acme/mixed/data",)
    assert modules.module_descriptors()[0].application_ids == ("acme/mixed/tool",)


@pytest.mark.parametrize("failing_family", ["composition", "application"])
def test_failed_mixed_import_publishes_neither_family(
    tmp_path: Path,
    failing_family: str,
) -> None:
    module = tmp_path / "mixed"
    write_composition(
        module,
        "data",
        runtime="class MissingRuntime: pass\n"
        if failing_family == "composition"
        else COMPOSITION_RUNTIME,
    )
    write_application(
        module,
        "tool",
        runtime="class MissingRuntime: pass\n"
        if failing_family == "application"
        else APPLICATION_RUNTIME,
    )
    modules, compositions, applications = runtime_components()

    with pytest.raises(Exception, match="runtime.py:Runtime"):
        modules.load_module(module, module_id="acme/mixed")

    assert modules.modules() == ()
    assert compositions.definitions() == ()
    assert applications.definitions() == ()


def test_application_contract_failure_rolls_back_staged_compositions(tmp_path: Path) -> None:
    module = tmp_path / "mixed"
    write_composition(module, "data")
    write_application(
        module,
        "tool",
        spec="""\
[app]
id = "tool"
[functions.run]
description = "Run it."
""",
    )
    modules, compositions, applications = runtime_components()

    with pytest.raises(Exception, match="does not implement declared function 'run'"):
        modules.load_module(module, module_id="acme/mixed")

    assert modules.modules() == ()
    assert compositions.definitions() == ()
    assert applications.definitions() == ()


def test_application_dependency_blocks_module_unload_before_registry_change(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base"
    dependent = tmp_path / "dependent"
    write_composition(base, "data")
    write_application(
        dependent,
        "tool",
        spec="""\
[app]
id = "tool"
[compositions.data]
use = "acme/base/data"
""",
        runtime="""\
class Runtime:
    def __init__(self, *, context, config, data):
        self.context = context
""",
    )
    modules, _, applications = runtime_components()
    loaded = modules.load_module(base, module_id="acme/base")
    modules.load_module(dependent, module_id="acme/dependent")

    with pytest.raises(ModuleComponentError, match="loaded application definition"):
        modules.unload_module("acme/base")

    assert modules.require_module("acme/base") is loaded
    assert applications.require_definition("acme/dependent/tool")


def test_application_graph_and_functions_are_validated_before_publication(
    tmp_path: Path,
) -> None:
    module = tmp_path / "mixed"
    write_composition(
        module,
        "data",
        spec="""\
[composition]
id = "data"
[functions.read]
description = "Read data."
""",
        runtime="""\
class Runtime:
    def __init__(self, *, context, config): pass
    def read(self): return "data"
""",
    )
    write_application(
        module,
        "base",
        spec="""\
[app]
id = "base"
[functions.ping]
description = "Ping."
""",
        runtime="""\
class Runtime:
    def __init__(self, *, context, config): pass
    def ping(self): return "pong"
""",
    )
    write_application(
        module,
        "tool",
        spec="""\
[app]
id = "tool"
[compositions.data]
use = "acme/mixed/data"
export = ["read"]
[apps.base]
use = "acme/mixed/base"
export = ["ping"]
""",
        runtime="""\
class Runtime:
    def __init__(self, *, context, config, data, base): pass
    def read(self): return self.data.read()
    def ping(self): return self.base.ping()
""",
    )
    modules, _, applications = runtime_components()

    modules.load_module(module, module_id="acme/mixed")
    graph = applications.describe_dependency_graph("acme/mixed/tool")
    descriptor = applications.describe_application("acme/mixed/tool")

    assert graph.nodes == ("acme/mixed/base", "acme/mixed/tool")
    assert [(edge.kind, edge.alias, edge.target) for edge in graph.edges] == [
        ("application", "base", "acme/mixed/base"),
        ("composition", "data", "acme/mixed/data"),
    ]
    assert [(item.id, item.origin) for item in descriptor.functions] == [
        ("ping", "base.ping"),
        ("read", "data.read"),
    ]


def test_application_dependency_cycle_is_rejected_without_publication(
    tmp_path: Path,
) -> None:
    module = tmp_path / "cycle"
    write_application(
        module,
        "first",
        spec="""\
[app]
id = "first"
[apps.other]
use = "acme/cycle/second"
""",
        runtime="""\
class Runtime:
    def __init__(self, *, context, config, other): pass
""",
    )
    write_application(
        module,
        "second",
        spec="""\
[app]
id = "second"
[apps.other]
use = "acme/cycle/first"
""",
        runtime="""\
class Runtime:
    def __init__(self, *, context, config, other): pass
""",
    )
    modules, _, applications = runtime_components()

    with pytest.raises(Exception, match="application dependency cycle"):
        modules.load_module(module, module_id="acme/cycle")

    assert modules.modules() == ()
    assert applications.definitions() == ()


def test_unload_reports_every_live_use_without_mutation(tmp_path: Path) -> None:
    module = tmp_path / "mixed"
    write_composition(module, "data")
    write_application(module, "tool")
    modules, compositions, applications = runtime_components()
    loaded = modules.load_module(module, module_id="acme/mixed")
    composition = compositions.create_instance(
        CompositionInstanceSpec("data", "acme/mixed/data", {}, tmp_path),
        owner_scope_id="z-owner",
    )
    application = applications.create_instance(
        ApplicationInstanceSpec("tool", "acme/mixed/tool", {}, tmp_path),
        owner_scope_id="a-owner",
    )

    with pytest.raises(ModuleComponentError) as captured:
        modules.unload_module("acme/mixed")

    message = str(captured.value)
    application_line = (
        "live application definition 'acme/mixed/tool' from module 'acme/mixed': "
        "scope='a-owner', instance='tool', root='tool'"
    )
    composition_line = (
        "live composition definition 'acme/mixed/data' from module 'acme/mixed': "
        "scope='z-owner', instance='data', root='data'"
    )
    assert application_line in message
    assert composition_line in message
    assert message.index(application_line) < message.index(composition_line)
    assert modules.require_module("acme/mixed") is loaded
    assert compositions.require_instance("z-owner", "data") is composition
    assert applications.require_instance("a-owner", "tool") is application

    applications.destroy_instance("a-owner", "tool")
    compositions.destroy_instance("z-owner", "data")
    assert modules.unload_module("acme/mixed") is loaded
