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
    ApplicationLifecycleError,
)
from dix.core.module.component import ModuleComponentError


def write_composition(
    module: Path,
    local_id: str,
    runtime: str,
) -> None:
    root = module / "compositions" / local_id
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(f'[composition]\nid = "{local_id}"\n')
    (root / "runtime.py").write_text(runtime)


def write_application(
    module: Path,
    local_id: str,
    spec: str,
    runtime: str,
) -> None:
    root = module / "apps" / local_id
    root.mkdir(parents=True)
    (root / "app.toml").write_text(spec)
    (root / "runtime.py").write_text(runtime)


def lifecycle_runtime(
    log: Path,
    label: str,
    *,
    init: str | None = None,
    cleanup: str | None = None,
) -> str:
    init_body = init or f"record('{label}.init')"
    cleanup_body = cleanup or f"record('{label}.cleanup')"
    return (
        "from pathlib import Path\n"
        f"LOG = Path({str(log)!r})\n"
        "def record(value):\n"
        "    with LOG.open('a') as stream: stream.write(value + '\\n')\n"
        "class Runtime:\n"
        "    def __init__(self, *, context, config): self.context = context\n"
        "    def init(self):\n"
        f"        {init_body}\n"
        "    def cleanup(self):\n"
        f"        {cleanup_body}\n"
    )


def app_runtime(
    log: Path,
    label: str,
    dependency_aliases: tuple[str, ...],
    *,
    start: str | None = None,
    stop: str | None = None,
) -> str:
    parameters = ", ".join(("context", "config", *dependency_aliases))
    start_body = start or f"record('{label}.start')"
    stop_body = stop or f"record('{label}.stop')"
    return (
        "from pathlib import Path\n"
        f"LOG = Path({str(log)!r})\n"
        "def record(value):\n"
        "    with LOG.open('a') as stream: stream.write(value + '\\n')\n"
        "class Runtime:\n"
        f"    def __init__(self, *, {parameters}): pass\n"
        "    def start(self):\n"
        f"        {start_body}\n"
        "    def stop(self):\n"
        f"        {stop_body}\n"
    )


def write_lifecycle_graph(
    module: Path,
    log: Path,
    *,
    child_composition_init: str | None = None,
    child_composition_cleanup: str | None = None,
    root_composition_init: str | None = None,
    root_composition_cleanup: str | None = None,
    child_start: str | None = None,
    child_stop: str | None = None,
    root_start: str | None = None,
    root_stop: str | None = None,
) -> None:
    write_composition(
        module,
        "child_data",
        lifecycle_runtime(
            log,
            "child.composition",
            init=child_composition_init,
            cleanup=child_composition_cleanup,
        ),
    )
    write_composition(
        module,
        "root_data",
        lifecycle_runtime(
            log,
            "root.composition",
            init=root_composition_init,
            cleanup=root_composition_cleanup,
        ),
    )
    write_application(
        module,
        "child",
        """\
[app]
id = "child"
[compositions.data]
use = "acme/lifecycle/child_data"
""",
        app_runtime(
            log,
            "child",
            ("data",),
            start=child_start,
            stop=child_stop,
        ),
    )
    write_application(
        module,
        "root",
        """\
[app]
id = "root"
[compositions.data]
use = "acme/lifecycle/root_data"
[apps.child]
use = "acme/lifecycle/child"
""",
        app_runtime(
            log,
            "root",
            ("data", "child"),
            start=root_start,
            stop=root_stop,
        ),
    )


def load_graph(module: Path):
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    compositions = registry.require("composition", CompositionComponent)
    applications = registry.require("application", ApplicationComponent)
    modules.load_module(module, module_id="acme/lifecycle")
    root = applications.create_instance(
        ApplicationInstanceSpec(
            "root",
            "acme/lifecycle/root",
            {},
            module.parent / "config",
        ),
        owner_scope_id="test",
    )
    return modules, compositions, applications, root


def test_start_and_stop_follow_full_dependency_order(tmp_path: Path) -> None:
    module = tmp_path / "module"
    log = tmp_path / "events"
    write_lifecycle_graph(module, log)
    _, compositions, applications, root = load_graph(module)

    applications.start_instance("test", "root")

    assert root.state == "active"
    assert log.read_text().splitlines() == [
        "child.composition.init",
        "root.composition.init",
        "child.start",
        "root.start",
    ]
    assert all(item.state == "initialized" for item in compositions.instances())

    applications.stop_instance("test", "root")

    assert root.state == "stopped"
    assert log.read_text().splitlines() == [
        "child.composition.init",
        "root.composition.init",
        "child.start",
        "root.start",
        "root.stop",
        "child.stop",
        "root.composition.cleanup",
        "child.composition.cleanup",
    ]
    assert all(item.state == "cleaned" for item in compositions.instances())
    with pytest.raises(ApplicationComponentError, match="current state"):
        applications.start_instance("test", "root")
    with pytest.raises(ApplicationComponentError, match="already stopped"):
        applications.stop_instance("test", "root")


def test_composition_init_failure_starts_no_app_and_rolls_back_graph(
    tmp_path: Path,
) -> None:
    module = tmp_path / "module"
    log = tmp_path / "events"
    write_lifecycle_graph(
        module,
        log,
        root_composition_init=("record('root.composition.init'); raise RuntimeError('init boom')"),
    )
    _, compositions, applications, _ = load_graph(module)

    with pytest.raises(ApplicationLifecycleError) as captured:
        applications.start_instance("test", "root")

    assert "init boom" in str(captured.value.errors[0])
    assert log.read_text().splitlines() == [
        "child.composition.init",
        "root.composition.init",
        "child.composition.cleanup",
    ]
    assert applications.instances() == ()
    assert compositions.instances() == ()


def test_start_failure_stops_started_apps_then_cleans_compositions(
    tmp_path: Path,
) -> None:
    module = tmp_path / "module"
    log = tmp_path / "events"
    write_lifecycle_graph(
        module,
        log,
        root_start="record('root.start'); raise RuntimeError('start boom')",
    )
    _, compositions, applications, _ = load_graph(module)

    with pytest.raises(ApplicationLifecycleError) as captured:
        applications.start_instance("test", "root")

    assert "start boom" in str(captured.value.errors[0])
    assert log.read_text().splitlines()[-3:] == [
        "child.stop",
        "root.composition.cleanup",
        "child.composition.cleanup",
    ]
    assert applications.instances() == ()
    assert compositions.instances() == ()


def test_stop_aggregates_failures_and_retries_only_unsuccessful_steps(
    tmp_path: Path,
) -> None:
    module = tmp_path / "module"
    log = tmp_path / "events"
    write_lifecycle_graph(module, log)
    _, compositions, applications, _ = load_graph(module)
    applications.start_instance("test", "root")
    root = applications.require_instance("test", "root")
    child = applications.require_instance("test", "root/child")
    root.runtime.fail_stop = True
    for composition in compositions.instances():
        composition.runtime.fail_cleanup = True

        original_cleanup = composition.runtime.cleanup

        def failing_cleanup(runtime=composition.runtime, original=original_cleanup):
            if runtime.fail_cleanup:
                raise RuntimeError(f"{runtime.context.composition_id} cleanup boom")
            return original()

        composition.runtime.cleanup = failing_cleanup
    original_root_stop = root.runtime.stop

    def failing_stop():
        if root.runtime.fail_stop:
            raise RuntimeError("root stop boom")
        return original_root_stop()

    root.runtime.stop = failing_stop

    with pytest.raises(ApplicationLifecycleError) as captured:
        applications.stop_instance("test", "root")

    assert len(captured.value.errors) == 3
    assert child.state == "stopped"
    root.runtime.fail_stop = False
    for composition in compositions.instances():
        composition.runtime.fail_cleanup = False
    before_retry = log.read_text().splitlines()

    applications.stop_instance("test", "root")

    retry_events = log.read_text().splitlines()[len(before_retry) :]
    assert retry_events == [
        "root.stop",
        "root.composition.cleanup",
        "child.composition.cleanup",
    ]


def test_destroy_and_module_unload_use_the_same_lifecycle_path(tmp_path: Path) -> None:
    module = tmp_path / "module"
    log = tmp_path / "events"
    write_lifecycle_graph(module, log)
    modules, compositions, applications, _ = load_graph(module)
    applications.start_instance("test", "root")

    modules.unload_module("acme/lifecycle")

    assert applications.instances() == ()
    assert compositions.instances() == ()
    assert log.read_text().splitlines()[-4:] == [
        "root.stop",
        "child.stop",
        "root.composition.cleanup",
        "child.composition.cleanup",
    ]


def test_lifecycle_only_apps_and_missing_hooks_are_valid(tmp_path: Path) -> None:
    module = tmp_path / "module"
    write_application(
        module,
        "child",
        '[app]\nid = "child"\n',
        "class Runtime:\n    def __init__(self, *, context, config): pass\n",
    )
    write_application(
        module,
        "root",
        '[app]\nid = "root"\n[apps.child]\nuse = "acme/lifecycle/child"\n',
        "class Runtime:\n    def __init__(self, *, context, config, child): pass\n",
    )
    _, _, applications, root = load_graph(module)

    applications.start_instance("test", "root")
    applications.stop_instance("test", "root")

    assert root.api.functions() == ()
    assert root.state == "stopped"


@pytest.mark.parametrize("hook", ["start", "stop"])
def test_async_application_lifecycle_hook_is_rejected_at_load(
    tmp_path: Path,
    hook: str,
) -> None:
    module = tmp_path / "module"
    write_application(
        module,
        "root",
        '[app]\nid = "root"\n',
        (
            "class Runtime:\n"
            "    def __init__(self, *, context, config): pass\n"
            f"    async def {hook}(self): pass\n"
        ),
    )
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)

    with pytest.raises(ModuleComponentError, match=rf"root\.{hook}"):
        modules.load_module(module, module_id="acme/lifecycle")
