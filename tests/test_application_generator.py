from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from dix.applications.generator import ApplicationGeneratorError, generate_runtime
from dix.applications.resolver import TrustedBuildApplicationResolver
from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec


def write_composition(module: Path, runtime: str) -> None:
    root = module / "compositions" / "base"
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(
        """[composition]
id = "base"
[functions.complex_call]
description = "Forward every parameter kind."
[functions.hidden]
description = "Not used by the generated app."
"""
    )
    (root / "runtime.py").write_text(runtime)


def write_application(module: Path, local_id: str, spec: str, runtime: str | None = None) -> Path:
    root = module / "apps" / local_id
    root.mkdir(parents=True)
    path = root / "app.toml"
    path.write_text(spec)
    if runtime is not None:
        (root / "runtime.py").write_text(runtime)
    return path


def write_dependencies(tmp_path: Path, composition_runtime: str | None = None) -> Path:
    module = tmp_path / "modules" / "acme" / "base"
    write_composition(
        module,
        composition_runtime
        or """class Runtime:
    def __init__(self, *, context, config): pass
    def complex_call(self, first: str, /, second: str = "default", *values: int, flag: bool = True, **extra: str) -> tuple:
        return first, second, values, flag, extra
    def hidden(self) -> str:
        return "hidden"
""",
    )
    write_application(
        module,
        "worker",
        """[app]
id = "worker"
[functions.async_call]
description = "Forward asynchronously."
[functions.hidden_app]
description = "Not used by the generated app."
""",
        """class Runtime:
    def __init__(self, *, context, config): pass
    async def async_call(self, value: str, *, suffix: str = "!") -> str:
        return value + suffix
    def hidden_app(self) -> str:
        return "hidden"
""",
    )
    return module


def write_target(tmp_path: Path) -> Path:
    module = tmp_path / "modules" / "acme" / "target"
    return write_application(
        module,
        "child",
        """[app]
id = "child"
[compositions.values]
use = "acme/base/base"
export = ["complex_call"]
[apps.worker]
use = "acme/base/worker"
export = ["async_call"]
[functions.complex_alias]
export = "values.complex_call"
description = "Alias the complex call."
[functions.async_alias]
export = "worker.async_call"
description = "Alias the async call."
[functions.local_value]
description = "Provide local behavior."
""",
    )


def test_generator_creates_protocols_constructor_wrappers_and_stub(tmp_path: Path) -> None:
    base_module = write_dependencies(tmp_path)
    spec = write_target(tmp_path)
    roots = (tmp_path / "modules",)

    with TrustedBuildApplicationResolver(roots) as resolver:
        target = generate_runtime(spec, resolver)
    source = target.read_text()

    assert "class ValuesCompositionApi(Protocol):" in source
    assert "class WorkerApplicationApi(Protocol):" in source
    assert "hidden" not in source
    assert "context: ApplicationRuntimeContext" in source
    assert "values: ValuesCompositionApi" in source
    assert "worker: WorkerApplicationApi" in source
    assert "def complex_call(self, first: str, /, second: str = 'default', *values: int" in source
    assert (
        "self.values.require('complex_call')(first, second, *values, flag=flag, **extra)" in source
    )
    assert "def complex_alias(self, first: str, /" in source
    assert "async def async_call" in source
    assert "return await self.worker.require('async_call')(value, suffix=suffix)" in source
    assert "async def async_alias" in source
    assert "def local_value(self) -> object:" in source
    assert "raise NotImplementedError" in source
    assert "def start" not in source
    compile(source, str(target), "exec")

    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(base_module, module_id="acme/base")
    modules.load_module(spec.parents[2], module_id="acme/target")
    root = applications.create_instance(
        ApplicationInstanceSpec("child", "acme/target/child", {}, tmp_path),
        owner_scope_id="owner",
    )
    assert root.api.complex_call("one", "two", 3, flag=False, key="value") == (
        "one",
        "two",
        (3,),
        False,
        {"key": "value"},
    )
    assert root.api.complex_alias("one") == ("one", "default", (), True, {})
    assert asyncio.run(root.api.async_call("hello", suffix="?")) == "hello?"
    assert asyncio.run(root.api.async_alias("hello")) == "hello!"
    with pytest.raises(NotImplementedError):
        root.api.local_value()


def test_generator_adds_application_lifecycle_only_when_requested(tmp_path: Path) -> None:
    write_dependencies(tmp_path)
    spec = write_target(tmp_path)
    with TrustedBuildApplicationResolver((tmp_path / "modules",)) as resolver:
        source = generate_runtime(spec, resolver, include_lifecycle=True).read_text()

    assert "def start(self) -> None:" in source
    assert "def stop(self) -> None:" in source


def test_generator_never_overwrites_runtime(tmp_path: Path) -> None:
    write_dependencies(tmp_path)
    spec = write_target(tmp_path)
    with TrustedBuildApplicationResolver((tmp_path / "modules",)) as resolver:
        target = generate_runtime(spec, resolver)
    original = target.read_text()

    with (
        TrustedBuildApplicationResolver((tmp_path / "modules",)) as resolver,
        pytest.raises(ApplicationGeneratorError, match="already exists"),
    ):
        generate_runtime(spec, resolver)

    assert target.read_text() == original


def test_unrepresentable_default_is_rejected_without_partial_runtime(tmp_path: Path) -> None:
    write_dependencies(
        tmp_path,
        composition_runtime="""SENTINEL = object()
class Runtime:
    def __init__(self, *, context, config): pass
    def complex_call(self, value=SENTINEL): return value
    def hidden(self): return None
""",
    )
    spec = write_target(tmp_path)

    with (
        TrustedBuildApplicationResolver((tmp_path / "modules",)) as resolver,
        pytest.raises(ApplicationGeneratorError, match="stable source"),
    ):
        generate_runtime(spec, resolver)

    assert (spec.parent / "runtime.py").exists() is False


def test_generator_ignores_incomplete_target_and_unrelated_sibling(tmp_path: Path) -> None:
    write_dependencies(tmp_path)
    spec = write_target(tmp_path)
    unrelated = spec.parents[1] / "unfinished"
    unrelated.mkdir()
    (unrelated / "app.toml").write_text('[app]\nid = "unfinished"\n')

    with TrustedBuildApplicationResolver((tmp_path / "modules",)) as resolver:
        target = generate_runtime(spec, resolver)

    assert target.exists()
    assert not any(name.startswith("_dix_app_build_") for name in sys.modules)
    assert not any(name.startswith("_dix_build_") for name in sys.modules)


def test_missing_used_dependency_writes_no_partial_runtime(tmp_path: Path) -> None:
    spec = write_target(tmp_path)

    with (
        TrustedBuildApplicationResolver((tmp_path / "modules",)) as resolver,
        pytest.raises(ApplicationGeneratorError, match="not present"),
    ):
        generate_runtime(spec, resolver)

    assert (spec.parent / "runtime.py").exists() is False


def test_declared_dependency_without_exports_still_requires_a_runtime(tmp_path: Path) -> None:
    module = tmp_path / "modules" / "acme" / "base"
    root = module / "compositions" / "empty"
    root.mkdir(parents=True)
    (root / "composition.toml").write_text('[composition]\nid = "empty"\n')
    target = tmp_path / "target"
    spec = write_application(
        target,
        "child",
        """[app]
id = "child"
[compositions.empty]
use = "acme/base/empty"
""",
    )

    with (
        TrustedBuildApplicationResolver((tmp_path / "modules",)) as resolver,
        pytest.raises(ApplicationGeneratorError, match="runtime"),
    ):
        generate_runtime(spec, resolver)

    assert (spec.parent / "runtime.py").exists() is False


def test_duplicate_application_dependency_across_roots_is_rejected(tmp_path: Path) -> None:
    for root_name in ("one", "two"):
        module = tmp_path / root_name / "acme" / "base"
        write_composition(
            module,
            "class Runtime:\n"
            "    def __init__(self, *, context, config): pass\n"
            "    def complex_call(self): return None\n"
            "    def hidden(self): return None\n",
        )
        write_application(
            module,
            "worker",
            '[app]\nid = "worker"\n[functions.async_call]\ndescription = "Call."\n',
            "class Runtime:\n"
            "    def __init__(self, *, context, config): pass\n"
            "    def async_call(self): return None\n",
        )
    target_module = tmp_path / "target"
    spec = write_application(
        target_module,
        "child",
        """[app]
id = "child"
[apps.worker]
use = "acme/base/worker"
export = ["async_call"]
""",
    )

    with (
        TrustedBuildApplicationResolver((tmp_path / "one", tmp_path / "two")) as resolver,
        pytest.raises(ApplicationGeneratorError, match="duplicate application dependency"),
    ):
        generate_runtime(spec, resolver)

    assert (spec.parent / "runtime.py").exists() is False
