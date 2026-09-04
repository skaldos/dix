from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from dix.compositions.generator import CompositionGeneratorError, generate_runtime
from dix.core import CompositionComponent, create_core_component_registry
from dix.core.composition import CompositionInstanceSpec


def write_composition(module: Path, local_id: str, body: str, runtime: str) -> Path:
    root = module / "compositions" / local_id
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(body)
    (root / "runtime.py").write_text(runtime)
    return root


def component_with_base(tmp_path: Path, runtime: str | None = None) -> CompositionComponent:
    module = tmp_path / "base-module"
    write_composition(
        module,
        "base",
        """[composition]
id = "base"
[functions.complex_call]
description = "Forward every parameter kind."
[functions.async_call]
description = "Forward asynchronously."
[functions.hidden]
description = "Not consumed by the generated child."
""",
        runtime
        or """class Runtime:
    def __init__(self, *, context, config): pass

    def complex_call(self, first: str, /, second: str = "default", *values: int, flag: bool = True, **extra: str) -> tuple:
        return first, second, values, flag, extra

    async def async_call(self, value: str, *, suffix: str = "!") -> str:
        return value + suffix

    def hidden(self) -> str:
        return "hidden"
""",
    )
    registry = create_core_component_registry()
    compositions = registry.require("composition", CompositionComponent)
    compositions.load_module(module, module_id="acme/base")
    return compositions


def write_child_source(tmp_path: Path) -> Path:
    module = tmp_path / "child-module"
    root = module / "compositions" / "child"
    root.mkdir(parents=True)
    spec = root / "composition.toml"
    spec.write_text(
        """[composition]
id = "child"
[components]
model = "datamodel"
[compositions.base]
use = "acme/base/base"
export = ["complex_call", "async_call"]
[functions.complex_alias]
export = "base.complex_call"
description = "Alias complex call."
[functions.local_value]
description = "Provide local behavior."
"""
    )
    return spec


def test_generator_creates_protocol_constructor_wrappers_and_stub(tmp_path: Path) -> None:
    compositions = component_with_base(tmp_path)
    spec = write_child_source(tmp_path)

    target = generate_runtime(spec, compositions)
    source = target.read_text()

    assert "class BaseApi(Protocol):" in source
    assert "def hidden" not in source
    assert "context: CompositionRuntimeContext" in source
    assert "model: object" in source
    assert "base: BaseApi" in source
    assert "def complex_call(self, first: str, /, second: str = 'default', *values: int" in source
    assert "self.base.complex_call(first, second, *values, flag=flag, **extra)" in source
    assert "def complex_alias(self, first: str, /" in source
    assert "async def async_call" in source
    assert "return await self.base.async_call(value, suffix=suffix)" in source
    assert "def local_value(self) -> object:" in source
    assert "raise NotImplementedError" in source
    compile(source, str(target), "exec")

    compositions.load_module(spec.parents[2], module_id="acme/child")
    root = compositions.create_instance(
        CompositionInstanceSpec("child", "acme/child/child", {}, tmp_path),
        owner_scope_id="owner",
    )
    assert root.api.complex_call("one", "two", 3, 4, flag=False, key="value") == (
        "one",
        "two",
        (3, 4),
        False,
        {"key": "value"},
    )
    assert root.api.complex_alias("one") == ("one", "default", (), True, {})
    assert asyncio.run(root.api.async_call("hello", suffix="?")) == "hello?"
    with pytest.raises(NotImplementedError):
        root.api.local_value()


def test_generator_adds_lifecycle_only_when_requested(tmp_path: Path) -> None:
    compositions = component_with_base(tmp_path)
    spec = write_child_source(tmp_path)

    source = generate_runtime(spec, compositions, include_lifecycle=True).read_text()

    assert "def start(self) -> None:" in source
    assert "def stop(self) -> None:" in source


def test_generator_never_overwrites_runtime(tmp_path: Path) -> None:
    compositions = component_with_base(tmp_path)
    spec = write_child_source(tmp_path)
    target = generate_runtime(spec, compositions)
    original = target.read_text()

    with pytest.raises(CompositionGeneratorError, match="already exists"):
        generate_runtime(spec, compositions)

    assert target.read_text() == original


def test_unrepresentable_default_is_rejected_without_partial_runtime(tmp_path: Path) -> None:
    compositions = component_with_base(
        tmp_path,
        runtime="""SENTINEL = object()
class Runtime:
    def __init__(self, *, context, config): pass
    def complex_call(self, value=SENTINEL): return value
    async def async_call(self, value): return value
    def hidden(self): return None
""",
    )
    spec = write_child_source(tmp_path)
    target = spec.parent / "runtime.py"

    with pytest.raises(CompositionGeneratorError, match="stable source"):
        generate_runtime(spec, compositions)

    assert target.exists() is False


def test_generated_annotation_falls_back_to_object_when_not_stably_importable(
    tmp_path: Path,
) -> None:
    compositions = component_with_base(
        tmp_path,
        runtime="""from pathlib import Path
class Runtime:
    def __init__(self, *, context, config): pass
    def complex_call(self, value: Path) -> Path: return value
    async def async_call(self, value): return value
    def hidden(self): return None
""",
    )
    spec = write_child_source(tmp_path)

    source = generate_runtime(spec, compositions).read_text()

    assert "complex_call(self, value: object) -> object" in source
