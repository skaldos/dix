from __future__ import annotations

from pathlib import Path

import pytest

from dix.core import (
    ApplicationComponent,
    CompositionComponent,
    ModuleComponent,
    create_core_component_registry,
)
from dix.core.application import (
    ApplicationComponentError,
    ApplicationInstanceSpec,
)
from dix.core.module.component import ModuleComponentError


def write_composition(module: Path, local_id: str, spec: str, runtime: str) -> None:
    root = module / "compositions" / local_id
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(spec)
    (root / "runtime.py").write_text(runtime)


def write_application(module: Path, local_id: str, spec: str, runtime: str) -> None:
    root = module / "apps" / local_id
    root.mkdir(parents=True)
    (root / "app.toml").write_text(spec)
    (root / "runtime.py").write_text(runtime)


def write_runtime_graph(module: Path) -> None:
    write_composition(
        module,
        "formatter",
        """\
[composition]
id = "formatter"
[functions.format]
description = "Format a value."
""",
        """\
class Runtime:
    def __init__(self, *, context, config):
        self.context = context
        self.config = config
    def format(self, value: str) -> str:
        return f"formatted:{value}"
""",
    )
    write_application(
        module,
        "child",
        """\
[app]
id = "child"
[compositions.formatter]
use = "acme/runtime/formatter"
export = ["format"]
[functions.child_value]
description = "Return child state."
""",
        """\
class Runtime:
    def __init__(self, *, context, config, formatter):
        self.context = context
        self.config = config
        self.formatter = formatter
    def format(self, value: str) -> str:
        return self.formatter.format(value)
    def child_value(self) -> str:
        return self.config.get("value", "child")
    def hidden(self):
        return "hidden"
""",
    )
    write_application(
        module,
        "root",
        """\
[app]
id = "root"
[compositions.formatter]
use = "acme/runtime/formatter"
config = { owner = "root" }
export = ["format"]
[apps.child]
use = "acme/runtime/child"
config = { value = "configured-child" }
export = ["child_value"]
[functions.render]
description = "Use the complete child API without re-exporting its format function."
[functions.render_alias]
export = "child.format"
description = "Expose child formatting under a new name."
""",
        """\
class Runtime:
    def __init__(self, *, context, config, formatter, child):
        self.context = context
        self.config = config
        self.formatter = formatter
        self.child = child
    def format(self, value: str) -> str:
        return self.formatter.format(value)
    def child_value(self) -> str:
        return self.child.child_value()
    def render(self, value: str) -> str:
        return f"root:{self.child.format(value)}"
    def render_alias(self, value: str) -> str:
        return self.child.format(value)
    def hidden(self):
        return "hidden"
""",
    )


def runtime_components(module: Path):
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    compositions = registry.require("composition", CompositionComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(module, module_id="acme/runtime")
    return modules, compositions, applications


def create_root(applications: ApplicationComponent, tmp_path: Path, instance_id="root"):
    return applications.create_instance(
        ApplicationInstanceSpec(
            instance_id,
            "acme/runtime/root",
            {"request": instance_id},
            tmp_path / "caller",
        ),
        owner_scope_id="test",
    )


def test_application_graph_injects_separate_apis_and_declared_functions(
    tmp_path: Path,
) -> None:
    module = tmp_path / "module"
    write_runtime_graph(module)
    _, _, applications = runtime_components(module)

    root = create_root(applications, tmp_path)
    child = applications.require_instance("test", "root/child")

    assert root.api.format("one") == "formatted:one"
    assert root.api.child_value() == "configured-child"
    assert root.api.render("two") == "root:formatted:two"
    assert root.api.render_alias("three") == "formatted:three"
    with pytest.raises(AttributeError):
        _ = root.api.hidden
    assert root.runtime.formatter is not root.runtime.child
    assert child.context.config_base_dir == (module / "apps" / "root").resolve()
    assert (
        child.compositions["formatter"].context.config_base_dir
        == (module / "apps" / "child").resolve()
    )
    assert root.context.config_base_dir == (tmp_path / "caller").resolve()


def test_aliases_and_root_graphs_are_fully_isolated(tmp_path: Path) -> None:
    module = tmp_path / "module"
    write_runtime_graph(module)
    write_application(
        module,
        "double",
        """\
[app]
id = "double"
[apps.first]
use = "acme/runtime/child"
[apps.second]
use = "acme/runtime/child"
""",
        """\
class Runtime:
    def __init__(self, *, context, config, first, second):
        self.first = first
        self.second = second
""",
    )
    _, compositions, applications = runtime_components(module)

    double = applications.create_instance(
        ApplicationInstanceSpec("double", "acme/runtime/double", {}, tmp_path),
        owner_scope_id="test",
    )
    first = create_root(applications, tmp_path, "first-root")
    second = create_root(applications, tmp_path, "second-root")

    assert double.runtime.first is not double.runtime.second
    assert applications.require_instance("test", "double/first").runtime is not (
        applications.require_instance("test", "double/second").runtime
    )
    assert first.runtime is not second.runtime
    assert first.compositions["formatter"].runtime is not (second.compositions["formatter"].runtime)
    assert len(compositions.instances()) == 6


def test_empty_api_and_local_same_name_overload_are_valid(tmp_path: Path) -> None:
    module = tmp_path / "module"
    write_runtime_graph(module)
    write_application(
        module,
        "empty",
        '[app]\nid = "empty"\n',
        "class Runtime:\n    def __init__(self, *, context, config): pass\n",
    )
    _, _, applications = runtime_components(module)

    empty = applications.create_instance(
        ApplicationInstanceSpec("empty", "acme/runtime/empty", {}, tmp_path),
        owner_scope_id="test",
    )
    root = create_root(applications, tmp_path)

    assert empty.api.functions() == ()
    with pytest.raises(AttributeError):
        _ = empty.api.anything
    assert root.api.render("value") == "root:formatted:value"
    assert applications.describe_function("acme/runtime/root", "render").origin is None


def test_failed_root_construction_rolls_back_app_and_composition_instances(
    tmp_path: Path,
) -> None:
    module = tmp_path / "module"
    write_runtime_graph(module)
    root_runtime = module / "apps" / "root" / "runtime.py"
    root_runtime.write_text(
        root_runtime.read_text().replace(
            "self.context = context",
            "raise RuntimeError('construction boom')",
            1,
        )
    )
    _, compositions, applications = runtime_components(module)

    with pytest.raises(ApplicationComponentError, match="construction boom"):
        create_root(applications, tmp_path)

    assert applications.instances() == ()
    assert compositions.instances() == ()


def test_destroy_removes_complete_inactive_application_and_composition_graph(
    tmp_path: Path,
) -> None:
    module = tmp_path / "module"
    write_runtime_graph(module)
    _, compositions, applications = runtime_components(module)
    create_root(applications, tmp_path)

    applications.destroy_instance("test", "root")

    assert applications.instances() == ()
    assert compositions.instances() == ()
    with pytest.raises(ApplicationComponentError, match="not found"):
        applications.require_instance("test", "root/child")


def test_application_to_recursive_composition_chain_is_local_and_callable(
    tmp_path: Path,
) -> None:
    module = tmp_path / "module"
    write_composition(
        module,
        "source",
        """\
[composition]
id = "source"
[functions.read]
description = "Read."
""",
        """\
class Runtime:
    def __init__(self, *, context, config): pass
    def read(self): return "value"
""",
    )
    write_composition(
        module,
        "formatter",
        """\
[composition]
id = "formatter"
[compositions.source]
use = "acme/runtime/source"
export = ["read"]
""",
        """\
class Runtime:
    def __init__(self, *, context, config, source): self.source = source
    def read(self): return f"formatted:{self.source.read()}"
""",
    )
    write_application(
        module,
        "root",
        """\
[app]
id = "root"
[compositions.formatter]
use = "acme/runtime/formatter"
export = ["read"]
""",
        """\
class Runtime:
    def __init__(self, *, context, config, formatter): self.formatter = formatter
    def read(self): return self.formatter.read()
""",
    )
    _, compositions, applications = runtime_components(module)

    root = create_root(applications, tmp_path)

    assert root.api.read() == "formatted:value"
    assert len(compositions.instances()) == 2


def test_module_unload_requires_explicit_application_graph_destroy(tmp_path: Path) -> None:
    module = tmp_path / "module"
    write_runtime_graph(module)
    modules, compositions, applications = runtime_components(module)
    create_root(applications, tmp_path)

    with pytest.raises(ModuleComponentError, match="live application definition"):
        modules.unload_module("acme/runtime")

    assert applications.instances()
    assert compositions.instances()
    applications.destroy_instance("test", "root")
    modules.unload_module("acme/runtime")

    assert applications.instances() == ()
    assert compositions.instances() == ()
    assert applications.definitions() == ()
