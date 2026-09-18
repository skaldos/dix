from __future__ import annotations

from pathlib import Path

import pytest

from dix.core import (
    CompositionComponent,
    ModuleComponent,
    create_core_component_registry,
)
from dix.core.composition import CompositionComponentError, CompositionInstanceSpec
from dix.modules import first_party_module_path

DEFAULT_MODEL = """
[knot]
id = "theme"
[fields.focused]
strand = "client_colors"
handler = "set_focused"
[fields.urgent]
strand = "client_colors"
handler = "set_urgent"
"""


def _write_composition(
    module: Path,
    local_id: str,
    *,
    body: str,
    runtime: str,
) -> Path:
    root = module / "compositions" / local_id
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(body)
    (root / "runtime.py").write_text(runtime)
    return root


def _write_owner_module(
    module: Path,
    *,
    model: str = DEFAULT_MODEL,
    configured_path: str = "knot.toml",
    strand_function: str = "execute",
    async_strand: bool = False,
    async_handler: bool = False,
) -> Path:
    strand_method = (
        f"    async def {strand_function}(self, value): return f'processed:{{value}}'\n"
        if async_strand
        else (
            f"    def {strand_function}(self, value):\n"
            "        self.calls.append(value)\n"
            "        return f'processed:{value}'\n"
        )
    )
    _write_composition(
        module,
        "client_colors",
        body=(
            '[composition]\nid = "client_colors"\n'
            f"[functions.{strand_function}]\n"
        ),
        runtime=(
            "class Runtime:\n"
            "    def __init__(self, *, context, config): self.calls = []\n"
            + strand_method
        ),
    )
    owner_root = _write_composition(
        module,
        "owner",
        body=(
            '[composition]\nid = "owner"\n'
            '[compositions.client_colors]\nuse = "acme/knot/client_colors"\n'
            '[compositions.knot]\nuse = "dix/norn/knot"\n'
            f"config = {{ model = {configured_path!r} }}\n"
            "[functions.execute]\n"
            "[functions.set_focused]\n"
            "[functions.set_urgent]\n"
        ),
        runtime=(
            "class Runtime:\n"
            "    def __init__(self, *, context, config, client_colors, knot):\n"
            "        self.knot = knot\n"
            "        self.calls = []\n"
            "        self.failure = LookupError('domain failure')\n"
            "    def execute(self, value): return self.knot.require('execute')(value)\n"
            + (
                "    async def set_focused(self, value): return value\n"
                if async_handler
                else (
                    "    def set_focused(self, value):\n"
                    "        self.calls.append(('focused', value))\n"
                    "        if value == 'processed:fail': raise self.failure\n"
                    "        return 'focused-result'\n"
                )
            )
            + "    def set_urgent(self, value):\n"
            "        self.calls.append(('urgent', value))\n"
            "        return 'urgent-result'\n"
        ),
    )
    (owner_root / "knot.toml").write_text(model)
    return owner_root


def _components() -> tuple[ModuleComponent, CompositionComponent]:
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    compositions = registry.require("composition", CompositionComponent)
    modules.load_module(first_party_module_path("dix/norn"), module_id="dix/norn")
    return modules, compositions


def _create(
    tmp_path: Path,
    *,
    model: str = DEFAULT_MODEL,
    configured_path: str = "knot.toml",
    strand_function: str = "execute",
    async_strand: bool = False,
    async_handler: bool = False,
):
    module = tmp_path / "module"
    owner_root = _write_owner_module(
        module,
        model=model,
        configured_path=configured_path,
        strand_function=strand_function,
        async_strand=async_strand,
        async_handler=async_handler,
    )
    modules, compositions = _components()
    modules.load_module(module, module_id="acme/knot")
    instance = compositions.create_instance(
        CompositionInstanceSpec("owner", "acme/knot/owner", {}, tmp_path),
        owner_scope_id="test",
    )
    return owner_root, compositions, instance


def _root_cause(error: BaseException) -> BaseException:
    current = error
    while current.__cause__ is not None:
        current = current.__cause__
    return current


def test_knot_model_retains_declared_field_order_and_value_only_api(tmp_path: Path) -> None:
    owner_root, compositions, _instance = _create(tmp_path)
    knot = compositions.require_instance("test", "owner/knot")

    assert {item.id for item in knot.api.functions()} == {"execute"}
    assert tuple(knot.api.describe("execute").signature.parameters) == ("value",)
    assert knot.runtime.specification.id == "theme"
    assert knot.runtime.specification.path == owner_root / "knot.toml"
    assert tuple(field.name for field in knot.runtime.specification.fields) == (
        "focused",
        "urgent",
    )
    assert knot.runtime.specification.fields[0].strand == "client_colors"
    assert knot.runtime.specification.fields[0].handler == "set_focused"


def test_execute_uses_model_order_and_ignores_missing_and_unknown_fields(
    tmp_path: Path,
) -> None:
    _owner_root, compositions, instance = _create(tmp_path)

    result = instance.api.require("execute")(
        {"unknown": 9, "urgent": "u", "focused": "f"}
    )

    assert result == {"focused": "focused-result", "urgent": "urgent-result"}
    strand = compositions.require_instance("test", "owner/client_colors")
    assert strand.runtime.calls == ["f", "u"]
    assert instance.runtime.calls == [
        ("focused", "processed:f"),
        ("urgent", "processed:u"),
    ]
    assert instance.api.require("execute")({}) == {}


def test_execute_rejects_non_mapping_without_calls(tmp_path: Path) -> None:
    _owner_root, compositions, instance = _create(tmp_path)

    with pytest.raises(Exception, match="input must be a mapping") as captured:
        instance.api.require("execute")([])

    assert type(captured.value).__name__ == "KnotInputError"
    strand = compositions.require_instance("test", "owner/client_colors")
    assert strand.runtime.calls == []
    assert instance.runtime.calls == []


def test_execute_preserves_handler_error_identity_and_stops(tmp_path: Path) -> None:
    _owner_root, compositions, instance = _create(tmp_path)
    expected = instance.runtime.failure

    with pytest.raises(LookupError) as captured:
        instance.api.require("execute")({"focused": "fail", "urgent": "u"})

    assert captured.value is expected
    strand = compositions.require_instance("test", "owner/client_colors")
    assert strand.runtime.calls == ["fail"]
    assert instance.runtime.calls == [("focused", "processed:fail")]


@pytest.mark.parametrize(
    "model,match",
    [
        ("[knot]\nid='x'\nextra=true\n[fields.a]\nstrand='s'\nhandler='h'\n", "unknown"),
        ("[knot]\nid='x'\n[fields]\n", "must not be empty"),
        ("[knot]\nid='x'\n[fields.'bad.name']\nstrand='s'\nhandler='h'\n", "flat identifier"),
        ("[knot]\nid='x'\n[fields.a]\nstrand='bad.name'\nhandler='h'\n", "flat identifier"),
        ("[knot]\nid='x'\n[fields.a]\nstrand='s'\nhandler='bad.name'\n", "flat identifier"),
        ("[knot]\nid='x'\n[fields.a]\nstrand='s'\nhandler='execute'\n", "must not reference"),
        ("[knot]\nid='x'\n[fields.a]\nstrand='s'\nhandler='h'\nextra=true\n", "unknown"),
    ],
)
def test_knot_model_rejects_invalid_contracts(
    tmp_path: Path,
    model: str,
    match: str,
) -> None:
    with pytest.raises(CompositionComponentError) as captured:
        _create(tmp_path, model=model)
    assert match in str(_root_cause(captured.value))


@pytest.mark.parametrize("configured", ["missing.toml", "directory", "../outside.toml"])
def test_knot_model_path_rejects_missing_directory_and_escape(
    tmp_path: Path,
    configured: str,
) -> None:
    module = tmp_path / "module"
    owner_root = _write_owner_module(module, configured_path=configured)
    (owner_root / "directory").mkdir()
    (owner_root.parent / "outside.toml").write_text(DEFAULT_MODEL)
    modules, compositions = _components()
    modules.load_module(module, module_id="acme/knot")

    with pytest.raises(CompositionComponentError) as captured:
        compositions.create_instance(
            CompositionInstanceSpec("owner", "acme/knot/owner", {}, tmp_path),
            owner_scope_id="test",
        )
    assert "path" in str(_root_cause(captured.value))


def test_knot_model_path_rejects_absolute_and_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside.toml"
    outside.write_text(DEFAULT_MODEL)
    module = tmp_path / "module"
    owner_root = _write_owner_module(module, configured_path="link.toml")
    modules, compositions = _components()
    modules.load_module(module, module_id="acme/knot")
    (owner_root / "link.toml").symlink_to(outside)

    with pytest.raises(CompositionComponentError) as captured:
        compositions.create_instance(
            CompositionInstanceSpec("owner", "acme/knot/owner", {}, tmp_path),
            owner_scope_id="test",
        )
    assert "escapes" in str(_root_cause(captured.value))

    other = tmp_path / "absolute-module"
    _write_owner_module(other, configured_path=str(outside))
    modules, compositions = _components()
    modules.load_module(other, module_id="acme/knot")
    with pytest.raises(CompositionComponentError) as captured:
        compositions.create_instance(
            CompositionInstanceSpec("owner", "acme/knot/owner", {}, tmp_path),
            owner_scope_id="test",
        )
    assert "relative" in str(_root_cause(captured.value))


@pytest.mark.parametrize(
    ("model", "strand_function", "async_strand", "async_handler", "match"),
    [
        (
            "[knot]\nid='x'\n[fields.a]\nstrand='missing'\nhandler='set_focused'\n",
            "execute",
            False,
            False,
            "does not declare composition dependency alias: missing",
        ),
        (
            "[knot]\nid='x'\n[fields.a]\nstrand='client_colors'\nhandler='missing'\n",
            "execute",
            False,
            False,
            "undeclared owner function missing",
        ),
        (DEFAULT_MODEL, "validate", False, False, "undeclared dependency client_colors.execute"),
        (DEFAULT_MODEL, "execute", True, False, "synchronous: dependency client_colors.execute"),
        (DEFAULT_MODEL, "execute", False, True, "synchronous: owner function set_focused"),
    ],
)
def test_invalid_owner_bindings_abort_before_graph_visibility(
    tmp_path: Path,
    model: str,
    strand_function: str,
    async_strand: bool,
    async_handler: bool,
    match: str,
) -> None:
    module = tmp_path / "module"
    _write_owner_module(
        module,
        model=model,
        strand_function=strand_function,
        async_strand=async_strand,
        async_handler=async_handler,
    )
    modules, compositions = _components()
    modules.load_module(module, module_id="acme/knot")

    with pytest.raises(CompositionComponentError, match=match):
        compositions.create_instance(
            CompositionInstanceSpec("owner", "acme/knot/owner", {}, tmp_path),
            owner_scope_id="test",
        )
    assert compositions.instances(scope_id="test") == ()


def test_knot_cannot_be_created_as_a_root_without_an_owner(tmp_path: Path) -> None:
    (tmp_path / "knot.toml").write_text(DEFAULT_MODEL)
    _modules, compositions = _components()

    with pytest.raises(CompositionComponentError, match="requires an immediate"):
        compositions.create_instance(
            CompositionInstanceSpec(
                "knot",
                "dix/norn/knot",
                {"model": "knot.toml"},
                tmp_path,
            ),
            owner_scope_id="test",
        )

    assert compositions.instances(scope_id="test") == ()
