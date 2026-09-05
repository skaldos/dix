from __future__ import annotations

from pathlib import Path

from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec


FUNCTION_IDS = ("cleanup", "init", "start", "stop")


def test_previous_lifecycle_names_are_explicit_application_functions(
    tmp_path: Path,
) -> None:
    module = tmp_path / "module"
    root = module / "apps" / "operations"
    root.mkdir(parents=True)
    marker = tmp_path / "calls"
    declarations = "\n".join(
        f"[functions.{function_id}]\ndescription = \"Explicit {function_id}.\""
        for function_id in FUNCTION_IDS
    )
    (root / "app.toml").write_text(f'[app]\nid = "operations"\n{declarations}\n')
    methods = "\n".join(
        "    def {name}(self):\n"
        "        with self.marker.open('a') as stream: stream.write('{name}\\n')\n".format(
            name=function_id
        )
        for function_id in FUNCTION_IDS
    )
    (root / "runtime.py").write_text(
        "from pathlib import Path\n"
        "class Runtime:\n"
        "    def __init__(self, *, context, config):\n"
        "        self.marker = Path(config['marker'])\n"
        f"{methods}"
    )
    registry = create_core_component_registry()
    modules = registry.require("module", ModuleComponent)
    applications = registry.require("application", ApplicationComponent)

    modules.load_module(module, module_id="acme/operations")
    instance = applications.create_instance(
        ApplicationInstanceSpec(
            "operations",
            "acme/operations/operations",
            {"marker": str(marker)},
            tmp_path,
        ),
        owner_scope_id="test",
    )

    assert not marker.exists()
    assert tuple(item.id for item in instance.api.functions()) == FUNCTION_IDS
    for function_id in FUNCTION_IDS:
        instance.api.require(function_id)()
    assert marker.read_text().splitlines() == list(FUNCTION_IDS)

    applications.destroy_instance("test", "operations")

    assert marker.read_text().splitlines() == list(FUNCTION_IDS)
    assert applications.instances() == ()
    assert not hasattr(applications, "start_instance")
    assert not hasattr(applications, "stop_instance")
