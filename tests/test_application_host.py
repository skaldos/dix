from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from dix.core import (
    ApplicationComponent,
    CompositionComponent,
    ElementBinding,
    ElementResult,
    ElementSpec,
    ModelDefinition,
    ModuleComponent,
    create_core_component_registry,
)
from dix.core.composition import CompositionInstanceSpec

REPOSITORY = Path(__file__).resolve().parents[1]
APP_MODULE = REPOSITORY / "examples" / "modules" / "dix" / "core" / "app"


def write_target(module: Path, marker: Path) -> None:
    root = module / "apps" / "target"
    root.mkdir(parents=True)
    (root / "app.toml").write_text(
        """[app]
id = "target"

[functions.render]
description = "Render one value."

[functions.async_render]
description = "Render one value asynchronously."

[functions.fail]
description = "Fail after construction."

[functions.mixed]
description = "Exercise every fixed Python parameter kind."

[functions.variadic]
description = "Exercise variadic Python binding."

[functions.bad_output]
description = "Return a value incompatible with the declared output."
"""
    )
    (root / "runtime.py").write_text(
        f"""from pathlib import Path

class Runtime:
    def __init__(self, *, context, config):
        self.marker = Path({str(marker)!r})
        self.marker.write_text(self.marker.read_text() + "create\\n" if self.marker.exists() else "create\\n")

    def render(self, *, value: str, count: int = 1) -> str:
        return value * count

    async def async_render(self, *, value: str) -> str:
        return value

    def fail(self, *, value: str) -> str:
        raise RuntimeError(value)

    def mixed(self, positional: str, /, count: int = 1, *, upper: bool = False) -> str:
        value = positional * count
        return value.upper() if upper else value

    def variadic(self, prefix: str, *values, **metadata) -> str:
        return prefix + ":" + ",".join(values) + ":" + str(metadata["suffix"])

    def bad_output(self) -> str:
        return 7
"""
    )


def host_runtime(tmp_path: Path):
    target = tmp_path / "target"
    marker = tmp_path / "marker"
    write_target(target, marker)
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    modules.load_module(APP_MODULE, module_id="dix/core/app")
    modules.load_module(target, module_id="test/target")
    compositions = registry.require("composition", CompositionComponent)
    applications = registry.require("application", ApplicationComponent)
    host = compositions.create_instance(
        CompositionInstanceSpec("host", "dix/core/app/host", {}, tmp_path),
        owner_scope_id="test",
    )
    return host, applications, marker


def test_host_describes_and_executes_sync_and_async_calls_without_leaks(tmp_path: Path) -> None:
    host, applications, marker = host_runtime(tmp_path)

    descriptor = host.api.describe_application("test/target/target")
    function = host.api.describe_function("test/target/target", "render")
    assert descriptor.functions[0].application_id == "test/target/target"
    assert function.contract.input_model.schema["count"].type == "integer"

    assert asyncio.run(
        host.api.execute(
            "test/target/target",
            "render",
            kwargs={"value": "x"},
        )
    ) == "x"
    registrations = host.runtime.datamodel.registration_count
    assert asyncio.run(
        host.api.execute(
            "test/target/target",
            "render",
            kwargs={"value": "cached"},
        )
    ) == "cached"
    assert host.runtime.datamodel.registration_count == registrations
    assert asyncio.run(
        host.api.execute(
            "test/target/target",
            "async_render",
            kwargs={"value": "async"},
        )
    ) == "async"
    assert applications.instances() == ()
    assert asyncio.run(
        host.api.execute(
            "test/target/target",
            "mixed",
            args=("m",),
            kwargs={"upper": True},
        )
    ) == "M"
    assert asyncio.run(
        host.api.execute(
            "test/target/target",
            "variadic",
            args=("v", "a", "b"),
            kwargs={"suffix": 3},
        )
    ) == "v:a,b:3"
    assert marker.read_text().splitlines() == ["create"] * 5


def test_host_rejects_bad_input_before_construction_and_cleans_up_failures(
    tmp_path: Path,
) -> None:
    host, applications, marker = host_runtime(tmp_path)

    with pytest.raises(Exception, match="incompatible"):
        asyncio.run(
            host.api.execute(
                "test/target/target",
                "render",
                kwargs={"value": "x", "count": "bad"},
            )
        )
    assert not marker.exists()

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(
            host.api.execute(
                "test/target/target",
                "fail",
                kwargs={"value": "boom"},
            )
        )
    assert applications.instances() == ()
    assert marker.read_text() == "create\n"

    with pytest.raises(Exception, match="output is incompatible"):
        asyncio.run(
            host.api.execute(
                "test/target/target",
                "bad_output",
            )
        )
    assert applications.instances() == ()
    assert marker.read_text() == "create\ncreate\n"


@dataclass(frozen=True)
class _UpperProcessor:
    def decode(self, raw: Any) -> ElementResult:
        if not isinstance(raw, str):
            return ElementResult(None, False)
        return ElementResult(raw.upper(), True)


@dataclass(frozen=True)
class _UpperHandler:
    handler_id: str = "test.upper"

    def bind(self, spec, delegate):
        assert delegate is not None
        return _UpperProcessor()


def test_host_accepts_scoped_model_overrides_with_element_wrappers(tmp_path: Path) -> None:
    host, _, _ = host_runtime(tmp_path)
    descriptor = host.api.describe_function("test/target/target", "render")
    override = ModelDefinition(
        uid=uuid4(),
        name="test/upper",
        schema={"value": ElementSpec("string"), "count": ElementSpec("integer")},
    )
    model_uid = host.api.register_input_model(
        "test/target/target",
        "render",
        override,
        (
            ElementBinding(
                type_name="string",
                handler_id="test.upper",
                handler=_UpperHandler(),
                mode="wrap",
            ),
        ),
    )

    result = asyncio.run(
        host.api.execute(
            "test/target/target",
            "render",
            kwargs={"value": "custom", "count": 1},
            input_model_uid=model_uid,
        )
    )

    assert descriptor.contract.input_model.uid != override.uid
    assert result == "CUSTOM"


def test_host_model_overrides_do_not_leak_to_another_host_instance(tmp_path: Path) -> None:
    host, _, _ = host_runtime(tmp_path)
    compositions = host.runtime.application._compositions
    other = compositions.create_instance(
        CompositionInstanceSpec("other", "dix/core/app/host", {}, tmp_path),
        owner_scope_id="other",
    )
    override = ModelDefinition(
        uid=uuid4(),
        name="test/upper",
        schema={"value": ElementSpec("string"), "count": ElementSpec("integer")},
    )
    model_uid = host.api.register_input_model(
        "test/target/target",
        "render",
        override,
        (
            ElementBinding(
                type_name="string",
                handler_id="test.upper",
                handler=_UpperHandler(),
                mode="wrap",
            ),
        ),
    )

    with pytest.raises(Exception, match="not registered in this host"):
        asyncio.run(
            other.api.execute(
                "test/target/target",
                "render",
                kwargs={"value": "isolated", "count": 1},
                input_model_uid=model_uid,
            )
        )
    assert asyncio.run(
        other.api.execute(
            "test/target/target",
            "render",
            kwargs={"value": "isolated", "count": 1},
        )
    ) == "isolated"
