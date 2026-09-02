from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from dix.models import ComponentRenderModel, InterfaceRenderModel


class HtmlRenderer:
    def __init__(self) -> None:
        template_dir = Path(__file__).parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def render_interface(self, model: InterfaceRenderModel) -> str:
        template = self.env.get_template("interface.html")
        return template.render(model=model, title=model.title)

    def render_component(self, component: ComponentRenderModel) -> str:
        template = self.env.get_template(f"interactions/{component.interaction.role}.html")
        return template.render(component=component)

    def render_update_fragment(
        self, model: InterfaceRenderModel, component: ComponentRenderModel
    ) -> str:
        template = self.env.get_template("update_fragment.html")
        return template.render(model=model, component=component, title=model.title)
