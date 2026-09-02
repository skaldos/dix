from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from dix.models import ComponentSpec
from dix.runtime import InterfaceRuntime


class HtmlRenderer:
    def __init__(self) -> None:
        template_dir = Path(__file__).parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def render_interface(self, runtime: InterfaceRuntime) -> str:
        template = self.env.get_template("interface.html")
        component_specs = {component.id: component for component in runtime.spec.components}
        return template.render(runtime=runtime, model=runtime.model(), component_specs=component_specs)

    def render_component(self, runtime: InterfaceRuntime, component_id: str) -> str:
        component_specs = {component.id: component for component in runtime.spec.components}
        spec: ComponentSpec = component_specs[component_id]
        template = self.env.get_template(f"components/{spec.use}.html")
        return template.render(
            runtime=runtime,
            model=runtime.model(),
            component_id=component_id,
            component_spec=spec,
            component_state=runtime.components[component_id].state,
            component_output=runtime.components[component_id].output,
        )
