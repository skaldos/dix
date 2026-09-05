from __future__ import annotations

import json
from pathlib import Path

import pytest

from dix.applications.generator import generate_runtime
from dix.applications.resolver import TrustedBuildApplicationResolver
from dix.cli import main
from dix.core import (
    ApplicationComponent,
    CompositionComponent,
    ModuleComponent,
    create_core_component_registry,
)
from dix.core.application import (
    ApplicationInstanceSpec,
    ApplicationLifecycleError,
)

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
        ApplicationInstanceSpec(
            instance_id,
            "acme/demo/child",
            {},
            REPOSITORY,
        ),
        owner_scope_id=scope_id,
    )


def record_hook(
    runtime: object,
    hook: str,
    label: str,
    events: list[str],
    *,
    failure: str | None = None,
) -> None:
    original = getattr(runtime, hook)

    def wrapped() -> None:
        events.append(label)
        if failure is not None:
            raise RuntimeError(failure)
        original()

    setattr(runtime, hook, wrapped)


def instrument_graph(
    applications: ApplicationComponent,
    compositions: CompositionComponent,
    instance_id: str,
    events: list[str],
    *,
    fail_child_start: bool = False,
) -> None:
    child = applications.require_instance("e2e", instance_id)
    base = applications.require_instance("e2e", f"{instance_id}/base")
    composition_scope = f"application:e2e:{instance_id}/base"
    formatter = compositions.require_instance(composition_scope, "formatter")
    source = compositions.require_instance(composition_scope, "source")
    for runtime, hook, label in (
        (formatter.runtime, "init", "formatter.init"),
        (source.runtime, "init", "source.init"),
        (base.runtime, "start", "base.start"),
        (child.runtime, "start", "child.start"),
        (child.runtime, "stop", "child.stop"),
        (base.runtime, "stop", "base.stop"),
        (source.runtime, "cleanup", "source.cleanup"),
        (formatter.runtime, "cleanup", "formatter.cleanup"),
    ):
        record_hook(
            runtime,
            hook,
            label,
            events,
            failure="child start failed" if fail_child_start and label == "child.start" else None,
        )


def test_recursive_example_load_create_start_call_and_destroy() -> None:
    inspection, loaded, _, compositions, applications = load_example()

    assert [item.local_id for item in inspection.composition_definitions] == [
        "formatter",
        "value_source",
    ]
    assert [item.local_id for item in inspection.application_definitions] == [
        "base",
        "child",
        "lifecycle_only",
    ]
    assert set(loaded.compositions) == {
        "acme/demo/formatter",
        "acme/demo/value_source",
    }
    assert set(loaded.applications) == {
        "acme/demo/base",
        "acme/demo/child",
        "acme/demo/lifecycle_only",
    }
    assert applications.instances() == ()
    assert compositions.instances() == ()

    child = create_child(applications, "request")
    base = applications.require_instance("e2e", "request/base")
    assert child.state == "created"
    assert base.state == "created"
    assert child.runtime.started is False
    assert base.runtime.started is False
    assert all(item.state == "created" for item in compositions.instances())

    events: list[str] = []
    instrument_graph(applications, compositions, "request", events)
    applications.start_instance("e2e", "request")

    assert events == ["formatter.init", "source.init", "base.start", "child.start"]
    assert child.api.render("demo") == "formatted<value:demo>"
    assert child.api.require("describe")("demo") == "child[formatted<value:demo>]"
    with pytest.raises(AttributeError):
        _ = child.api.hidden

    applications.destroy_instance("e2e", "request")

    assert events == [
        "formatter.init",
        "source.init",
        "base.start",
        "child.start",
        "child.stop",
        "base.stop",
        "source.cleanup",
        "formatter.cleanup",
    ]
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

    applications.start_instance("e2e", "first")
    applications.start_instance("e2e", "second")
    assert first.api.require("describe")("same") == second.api.require("describe")("same")
    applications.destroy_instance("e2e", "first")
    applications.destroy_instance("e2e", "second")
    assert applications.instances() == ()
    assert compositions.instances() == ()


def test_failed_child_start_rolls_back_only_completed_steps() -> None:
    _, _, _, compositions, applications = load_example()
    create_child(applications, "failure")
    events: list[str] = []
    instrument_graph(
        applications,
        compositions,
        "failure",
        events,
        fail_child_start=True,
    )

    with pytest.raises(ApplicationLifecycleError, match="child start failed"):
        applications.start_instance("e2e", "failure")

    assert events == [
        "formatter.init",
        "source.init",
        "base.start",
        "child.start",
        "base.stop",
        "source.cleanup",
        "formatter.cleanup",
    ]
    assert "child.stop" not in events
    assert applications.instances() == ()
    assert compositions.instances() == ()


def test_lifecycle_only_application_has_an_empty_api() -> None:
    _, _, _, compositions, applications = load_example()
    root = applications.create_instance(
        ApplicationInstanceSpec(
            "lifecycle",
            "acme/demo/lifecycle_only",
            {},
            REPOSITORY,
        ),
        owner_scope_id="e2e",
    )

    assert root.api.functions() == ()
    applications.start_instance("e2e", "lifecycle")
    assert root.runtime.started is True
    applications.destroy_instance("e2e", "lifecycle")
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
        generate_runtime(spec, resolver, include_lifecycle=True)

    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(EXAMPLE_MODULE, module_id="acme/demo")
    modules.load_module(module, module_id="acme/generated")
    generated = applications.create_instance(
        ApplicationInstanceSpec("generated", "acme/generated/root", {}, tmp_path),
        owner_scope_id="generated",
    )
    applications.start_instance("generated", "generated")

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
