from __future__ import annotations

from pathlib import Path

import pytest

from dix.core.application import (
    ApplicationSpecError,
    inspect_application_source,
    inspect_spec,
)
from dix.core.module import ModuleSpecError, discover_modules, inspect_module


def write_application(
    module: Path,
    local_id: str,
    body: str | None = None,
    runtime: str = "class Runtime:\n    pass\n",
) -> Path:
    root = module / "apps" / local_id
    root.mkdir(parents=True)
    (root / "app.toml").write_text(body or f'[app]\nid = "{local_id}"\n')
    (root / "runtime.py").write_text(runtime)
    return root


def write_composition(module: Path, local_id: str) -> Path:
    root = module / "compositions" / local_id
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(
        f'[composition]\nid = "{local_id}"\n'
    )
    (root / "runtime.py").write_text("class Runtime:\n    pass\n")
    return root


def test_application_spec_parses_dependencies_exports_config_and_functions(
    tmp_path: Path,
) -> None:
    module = tmp_path / "bundle"
    root = write_application(
        module,
        "child",
        """[app]
id = "child"

[compositions.formatter]
use = "acme/tools/formatter"
config = { style = "brief" }
export = ["format"]

[apps.base]
use = "acme/runtime/base"
config = { enabled = true }
export = ["status"]

[functions.render]
export = "formatter.render"
description = "Render a value."

[functions.local]
description = "Local behavior."
""",
    )

    definition = inspect_spec(root / "app.toml", module_id="acme/demo")

    assert definition.id == "acme/demo/child"
    assert definition.compositions["formatter"].use == "acme/tools/formatter"
    assert dict(definition.compositions["formatter"].config) == {"style": "brief"}
    assert definition.compositions["formatter"].export == ("format",)
    assert definition.applications["base"].use == "acme/runtime/base"
    assert dict(definition.applications["base"].config) == {"enabled": True}
    assert definition.applications["base"].export == ("status",)
    assert definition.functions["render"].export == "formatter.render"
    assert definition.functions["local"].export is None


def test_application_source_does_not_require_generated_runtime(tmp_path: Path) -> None:
    root = tmp_path / "bundle" / "apps" / "pending"
    root.mkdir(parents=True)
    spec = root / "app.toml"
    spec.write_text('[app]\nid = "pending"\n')

    source = inspect_application_source(spec)

    assert source.local_id == "pending"
    assert source.application_root == root.resolve()


def test_mixed_module_is_inspected_without_importing_candidate_code(
    tmp_path: Path,
) -> None:
    module = tmp_path / "bundle"
    marker = tmp_path / "imported"
    write_composition(module, "worker")
    write_application(
        module,
        "service",
        runtime=(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).touch()\n"
            "raise RuntimeError('must not import')\n"
        ),
    )

    inspection = inspect_module(module, module_id="acme/bundle")

    assert [item.id for item in inspection.composition_definitions] == [
        "acme/bundle/worker"
    ]
    assert [item.id for item in inspection.application_definitions] == [
        "acme/bundle/service"
    ]
    assert marker.exists() is False


@pytest.mark.parametrize("family", ["composition", "application"])
def test_single_family_module_is_valid(tmp_path: Path, family: str) -> None:
    module = tmp_path / "bundle"
    if family == "composition":
        write_composition(module, "item")
    else:
        write_application(module, "item")

    inspection = inspect_module(module, module_id="acme/bundle")

    assert bool(inspection.composition_definitions) is (family == "composition")
    assert bool(inspection.application_definitions) is (family == "application")


def test_same_local_id_is_valid_across_artifact_families(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    write_composition(module, "shared")
    write_application(module, "shared")

    inspection = inspect_module(module, module_id="acme/bundle")

    assert inspection.composition_definitions[0].id == "acme/bundle/shared"
    assert inspection.application_definitions[0].id == "acme/bundle/shared"


def test_discovery_finds_app_only_module_and_stops_below_it(tmp_path: Path) -> None:
    trusted = tmp_path / "modules"
    outer = trusted / "acme" / "outer"
    write_application(outer, "root")
    write_application(outer / "nested" / "ignored", "hidden")
    write_application(trusted / "other" / "bundle", "visible")

    inspections = discover_modules([trusted])

    assert [item.id for item in inspections] == ["acme/outer", "other/bundle"]
    assert [item.id for item in inspections[0].application_definitions] == [
        "acme/outer/root"
    ]


def test_module_digest_covers_application_content(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    root = write_application(module, "item")
    first = inspect_module(module, module_id="acme/bundle").artifact_digest

    (root / "runtime.py").write_text("class Runtime:\n    changed = True\n")

    assert inspect_module(module, module_id="acme/bundle").artifact_digest != first


def test_empty_mixed_scaffold_is_not_a_module(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    (module / "compositions").mkdir(parents=True)
    (module / "apps").mkdir()

    with pytest.raises(ModuleSpecError, match="contains no definitions"):
        inspect_module(module, module_id="acme/bundle")


def test_application_id_must_match_directory(tmp_path: Path) -> None:
    root = write_application(
        tmp_path / "bundle",
        "actual",
        '[app]\nid = "other"\n',
    )

    with pytest.raises(ApplicationSpecError, match="does not match"):
        inspect_spec(root / "app.toml", module_id="acme/bundle")


def test_application_symlink_escape_is_rejected(tmp_path: Path) -> None:
    module = tmp_path / "bundle"
    root = write_application(module, "item")
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET = True\n")
    (root / "helper.py").symlink_to(outside)

    with pytest.raises(ModuleSpecError, match="module artifact escapes root"):
        inspect_module(module, module_id="acme/bundle")


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            """[app]
id = "child"
[components]
model = "datamodel"
""",
            "unknown key in application spec: components",
        ),
        (
            """[app]
id = "child"
[compositions.same]
use = "acme/base/item"
[apps.same]
use = "acme/base/item"
""",
            "both compositions and apps",
        ),
        (
            """[app]
id = "child"
[compositions.first]
use = "acme/base/item"
export = ["run"]
[apps.second]
use = "acme/base/item"
export = ["run"]
""",
            "duplicate effective function",
        ),
        (
            """[app]
id = "child"
[apps.base]
use = "acme/base/item"
export = ["run"]
[functions.run]
description = "collision"
""",
            "duplicate effective function",
        ),
        (
            """[app]
id = "child"
[functions.alias]
export = "missing.run"
""",
            "declared dependency alias",
        ),
        (
            """[app]
id = "child"
[functions.run]
params = ["value"]
""",
            "unknown key in functions.run: params",
        ),
        (
            """[app]
id = "child"
[functions.run]
returns = "string"
""",
            "unknown key in functions.run: returns",
        ),
    ],
)
def test_application_contract_rejects_ambiguous_or_redundant_specs(
    tmp_path: Path,
    body: str,
    message: str,
) -> None:
    root = write_application(tmp_path / "bundle", "child", body)

    with pytest.raises(ApplicationSpecError, match=message):
        inspect_spec(root / "app.toml", module_id="acme/bundle")


@pytest.mark.parametrize("function_id", ["start", "stop"])
def test_application_lifecycle_names_are_reserved(
    tmp_path: Path,
    function_id: str,
) -> None:
    root = write_application(
        tmp_path / "bundle",
        "child",
        f'[app]\nid = "child"\n[functions.{function_id}]\n',
    )

    with pytest.raises(ApplicationSpecError, match="invalid function id"):
        inspect_spec(root / "app.toml", module_id="acme/bundle")


@pytest.mark.parametrize("function_id", ["init", "cleanup"])
def test_composition_lifecycle_names_are_reserved_after_replacement(
    tmp_path: Path,
    function_id: str,
) -> None:
    module = tmp_path / "bundle"
    root = write_composition(module, "item")
    (root / "composition.toml").write_text(
        f'[composition]\nid = "item"\n[functions.{function_id}]\n'
    )

    with pytest.raises(ModuleSpecError, match="invalid function id"):
        inspect_module(module, module_id="acme/bundle")
