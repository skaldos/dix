from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dix.components import get_core_components
from dix.models import ComponentRuntime, InterfaceSpec, Session


class InterfaceRuntimeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interface_id: str
    title: str
    session: Session
    component_state: dict[str, dict[str, Any]]
    component_output: dict[str, dict[str, Any]]
    events: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class InterfaceRuntime:
    spec: InterfaceSpec
    session: Session
    components: dict[str, ComponentRuntime]
    events: list[dict[str, Any]] = field(default_factory=list)

    def model(self) -> InterfaceRuntimeModel:
        return InterfaceRuntimeModel(
            interface_id=self.spec.interface.id,
            title=self.spec.interface.title,
            session=self.session,
            component_state={key: value.state for key, value in self.components.items()},
            component_output={key: value.output for key, value in self.components.items()},
            events=self.events,
        )


class RuntimeStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], InterfaceRuntime] = {}

    def get_or_create(self, spec: InterfaceSpec, session: Session | None = None) -> InterfaceRuntime:
        final_session = session or Session()
        key = (spec.interface.id, final_session.id)
        if key not in self._items:
            components = get_core_components()
            self._items[key] = InterfaceRuntime(
                spec=spec,
                session=final_session,
                components={
                    component.id: components[component.use].create_runtime(component)
                    for component in spec.components
                },
            )
        return self._items[key]

    def update_component(
        self, runtime: InterfaceRuntime, component_id: str, data: dict[str, Any]
    ) -> InterfaceRuntime:
        spec_by_id = {component.id: component for component in runtime.spec.components}
        if component_id not in spec_by_id:
            raise KeyError(component_id)
        component_spec = spec_by_id[component_id]
        component = get_core_components()[component_spec.use]
        before = runtime.components[component_id]
        runtime.components[component_id] = component.update_runtime(component_spec, before, data)
        runtime.events.append({"component_id": component_id, "event": "changed"})
        return runtime
