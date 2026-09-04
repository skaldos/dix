from __future__ import annotations

from pathlib import Path

import pytest

from dix.core.composition import (
    CompositionSpecError,
    discover_modules,
    inspect_module,
    inspect_spec,
)


def write_composition(
    module: Path,
    local_id: str,
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


def test_inspect_module_reads_multiple_direct_compositions_without_importing(
    tmp_path: Path,
) -> None:
    module = tmp_path / "modules" / "acme" / "bundle"
    marker = tmp_path / "imported"
    write_composition(module, "second")
    write_composition(
        module,
        "first",
        runtime=f'raise RuntimeError("must not import")\nPath({str(marker)!r}).touch()\n',
    )

    inspection = inspect_module(module, module_id="acme/bundle")

    assert inspection.id == "acme/bundle"
    assert [item.id for item in inspection.definitions] == [
        "acme/bundle/first",
        "acme/bundle/second",
    ]
    assert len(inspection.artifact_digest) == 64
    assert marker.exists() is False


def test_spec_parses_dependencies_exports_and_local_functions(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    root = write_composition(
        module,
        "child",
        """[composition]
id = "child"

[components]
model = "datamodel"

[compositions.base]
use = "test/runtime/base"
export = ["echo"]
config = { strict = true }

[functions.echo_alias]
export = "base.echo"
description = "Alias echo."

[functions.local]
description = "Local function."
""",
    )

    definition = inspect_spec(root / "composition.toml", module_id="test/runtime")

    assert definition.id == "test/runtime/child"
    assert dict(definition.components) == {"model": "datamodel"}
    assert definition.compositions["base"].use == "test/runtime/base"
    assert definition.compositions["base"].export == ("echo",)
    assert dict(definition.compositions["base"].config) == {"strict": True}
    assert definition.functions["echo_alias"].export == "base.echo"
    assert definition.functions["local"].export is None


def test_discovery_uses_relative_module_ids_and_stops_below_module_root(
    tmp_path: Path,
) -> None:
    trusted = tmp_path / "modules"
    outer = trusted / "acme" / "outer"
    write_composition(outer, "base")
    write_composition(outer / "nested" / "ignored", "hidden")
    write_composition(trusted / "other" / "bundle", "visible")

    inspections = discover_modules([trusted])

    assert [item.id for item in inspections] == ["acme/outer", "other/bundle"]
    assert [item.id for item in inspections[0].definitions] == ["acme/outer/base"]


def test_nested_composition_directories_are_not_recursively_inspected(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    root = write_composition(module, "direct")
    write_composition(root / "nested", "ignored")

    inspection = inspect_module(module, module_id="acme/bundle")

    assert [item.local_id for item in inspection.definitions] == ["direct"]


def test_artifact_digest_changes_with_relevant_content_but_ignores_pyc(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    root = write_composition(module, "item")
    first = inspect_module(module, module_id="acme/bundle").artifact_digest
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "runtime.pyc").write_bytes(b"ignored")
    assert inspect_module(module, module_id="acme/bundle").artifact_digest == first
    (root / "runtime.py").write_text("class Runtime:\n    changed = True\n")
    assert inspect_module(module, module_id="acme/bundle").artifact_digest != first


def test_empty_module_is_not_inspectable(tmp_path: Path) -> None:
    module = tmp_path / "empty"
    (module / "compositions").mkdir(parents=True)

    with pytest.raises(CompositionSpecError, match="contains no compositions"):
        inspect_module(module, module_id="acme/empty")


@pytest.mark.parametrize(
    ("local_id", "spec_id"),
    [("actual", "other"), ("actual", "../escape")],
)
def test_local_id_must_be_safe_and_match_directory(
    tmp_path: Path,
    local_id: str,
    spec_id: str,
) -> None:
    module = tmp_path / "bundle"
    root = write_composition(
        module,
        local_id,
        f'[composition]\nid = "{spec_id}"\n',
    )

    with pytest.raises(CompositionSpecError):
        inspect_spec(root / "composition.toml", module_id="acme/bundle")


def test_missing_spec_and_runtime_report_paths(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    missing_spec = module / "compositions" / "missing_spec"
    missing_spec.mkdir(parents=True)
    with pytest.raises(CompositionSpecError, match="composition spec does not exist"):
        inspect_module(module, module_id="acme/bundle")

    (missing_spec / "composition.toml").write_text('[composition]\nid = "missing_spec"\n')
    with pytest.raises(CompositionSpecError, match="composition runtime does not exist"):
        inspect_module(module, module_id="acme/bundle")


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    outside = tmp_path / "outside"
    write_composition(outside / "module", "item")
    trusted.mkdir()
    (trusted / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(CompositionSpecError, match="escapes root"):
        discover_modules([trusted])


def test_module_artifact_symlink_escape_is_rejected(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    root = write_composition(module, "item")
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET = True\n")
    (root / "helper.py").symlink_to(outside)

    with pytest.raises(CompositionSpecError, match="module artifact escapes root"):
        inspect_module(module, module_id="acme/bundle")


def test_duplicate_module_ids_across_roots_are_rejected(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_composition(first / "acme" / "bundle", "item")
    write_composition(second / "acme" / "bundle", "item")

    with pytest.raises(CompositionSpecError, match="duplicate module id"):
        discover_modules([first, second])


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            """[composition]
id = "child"
[components]
same = "datamodel"
[compositions.same]
use = "acme/base/item"
""",
            "both components and compositions",
        ),
        (
            """[composition]
id = "child"
[compositions.first]
use = "acme/base/item"
export = ["echo"]
[compositions.second]
use = "acme/base/item"
export = ["echo"]
""",
            "duplicate effective function",
        ),
        (
            """[composition]
id = "child"
[compositions.base]
use = "acme/base/item"
export = ["echo"]
[functions.echo]
description = "collision"
""",
            "duplicate effective function",
        ),
        (
            """[composition]
id = "child"
[functions.alias]
export = "missing.echo"
""",
            "declared composition alias",
        ),
        (
            """[composition]
id = "child"
[compositions.base]
use = "acme/base/item"
export = ["*"]
""",
            "invalid compositions.base.export",
        ),
    ],
)
def test_alias_and_function_collisions_are_rejected(
    tmp_path: Path,
    body: str,
    message: str,
) -> None:
    module = tmp_path / "bundle"
    root = write_composition(module, "child", body)

    with pytest.raises(CompositionSpecError, match=message):
        inspect_spec(root / "composition.toml", module_id="acme/bundle")
