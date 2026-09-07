from __future__ import annotations

import json
from pathlib import Path

import pytest

from unstable.tools.application_authoring.generator import generate_runtime
from unstable.tools.application_authoring.resolver import TrustedBuildApplicationResolver
from unstable.tools.dix_cli.cli import main
from dix.core import (
    ApplicationComponent,
    CompositionComponent,
    ModuleComponent,
    create_core_component_registry,
)
from dix.core.application import ApplicationInstanceSpec

REPOSITORY = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = REPOSITORY / "examples" / "modules"
EXAMPLE_MODULE = EXAMPLE_ROOT / "acme" / "demo"


def load_example():
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    compositions = registry.require("composition", CompositionComponent)
    applications = registry.require("application", ApplicationComponent)
    inspection = modules.inspect_module(EXAMPLE_MODULE, module_id="acme/demo")
    loaded = modules.load_module(EXAMPLE_MODULE, module_id="acme/demo")
    return inspection, loaded, modules, compositions, applications


def create_child(
    applications: ApplicationComponent,
    instance_id: str,
    *,
    scope_id: str = "e2e",
):
    return applications.create_instance(
        ApplicationInstanceSpec(instance_id, "acme/demo/child", {}, REPOSITORY),
        owner_scope_id=scope_id,
    )


def test_recursive_example_load_create_call_and_destroy() -> None:
    inspection, loaded, _, compositions, applications = load_example()

    assert [item.local_id for item in inspection.composition_definitions] == [
        "formatter",
        "value_source",
    ]
    assert [item.local_id for item in inspection.application_definitions] == [
        "base",
        "child",
    ]
    assert set(loaded.compositions) == {
        "acme/demo/formatter",
        "acme/demo/value_source",
    }
    assert set(loaded.applications) == {"acme/demo/base", "acme/demo/child"}
    assert applications.instances() == ()
    assert compositions.instances() == ()

    child = create_child(applications, "request")
    assert child.api.render("demo") == "formatted<value:demo>"
    assert child.api.require("describe")("demo") == "child[formatted<value:demo>]"
    with pytest.raises(AttributeError):
        _ = child.api.hidden

    applications.destroy_instance("e2e", "request")
    assert applications.instances(scope_id="e2e") == ()
    assert compositions.instances() == ()


def test_recursive_root_graphs_are_fully_isolated() -> None:
    _, _, _, compositions, applications = load_example()
    first = create_child(applications, "first")
    second = create_child(applications, "second")
    first_base = applications.require_instance("e2e", "first/base")
    second_base = applications.require_instance("e2e", "second/base")

    assert first.runtime is not second.runtime
    assert first_base.runtime is not second_base.runtime
    assert first_base.compositions["formatter"].runtime is not (
        second_base.compositions["formatter"].runtime
    )
    assert first_base.compositions["source"].runtime is not (
        second_base.compositions["source"].runtime
    )
    assert first.api.require("describe")("same") == second.api.require("describe")("same")
    applications.destroy_instance("e2e", "first")
    applications.destroy_instance("e2e", "second")
    assert applications.instances() == ()
    assert compositions.instances() == ()


def test_generator_output_loads_through_the_productive_recursive_path(
    tmp_path: Path,
) -> None:
    module = tmp_path / "modules" / "acme" / "generated"
    root = module / "apps" / "root"
    root.mkdir(parents=True)
    spec = root / "app.toml"
    spec.write_text(
        """[app]
id = "root"
[apps.child]
use = "acme/demo/child"
export = ["describe"]
"""
    )
    with TrustedBuildApplicationResolver((EXAMPLE_ROOT, tmp_path / "modules")) as resolver:
        generate_runtime(spec, resolver)

    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(EXAMPLE_MODULE, module_id="acme/demo")
    modules.load_module(module, module_id="acme/generated")
    generated = applications.create_instance(
        ApplicationInstanceSpec("generated", "acme/generated/root", {}, tmp_path),
        owner_scope_id="generated",
    )

    assert generated.api.require("describe")("input") == "child[formatted<value:input>]"
    applications.destroy_instance("generated", "generated")
    assert applications.instances() == ()


def test_module_and_application_cli_match_core_descriptors(monkeypatch, capsys) -> None:
    _, loaded, _, _, applications = load_example()
    monkeypatch.chdir(REPOSITORY)

    assert main(["module", "show", "acme/demo", "--json"]) == 0
    module_payload = json.loads(capsys.readouterr().out)
    assert module_payload["artifact_digest"] == loaded.inspection.artifact_digest
    assert module_payload["composition_ids"] == sorted(loaded.compositions)
    assert module_payload["application_ids"] == sorted(loaded.applications)

    assert main(["app", "show", "acme/demo/child", "--json"]) == 0
    app_payload = json.loads(capsys.readouterr().out)
    descriptor = applications.describe_application("acme/demo/child")
    assert app_payload["definition"]["id"] == descriptor.definition.id
    assert [item["id"] for item in app_payload["functions"]] == [
        item.id for item in descriptor.functions
    ]

    assert main(["app", "graph", "acme/demo/child", "--json"]) == 0
    graph = json.loads(capsys.readouterr().out)
    assert graph["edges"] == [
        {
            "alias": "formatter",
            "kind": "composition",
            "source": "acme/demo/base",
            "target": "acme/demo/formatter",
        },
        {
            "alias": "source",
            "kind": "composition",
            "source": "acme/demo/base",
            "target": "acme/demo/value_source",
        },
        {
            "alias": "base",
            "kind": "application",
            "source": "acme/demo/child",
            "target": "acme/demo/base",
        },
    ]
    assert applications.instances() == ()
