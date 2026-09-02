from __future__ import annotations

from dix.elements.value import ValueState
from dix.models import ComponentDefinition, ComponentRuntime, ComponentSpec

from .base import Component


class InputComponent(Component):
    definition = ComponentDefinition(
        id="input",
        description="Text-like input component backed by the headless value element.",
        elements=["value"],
        outputs=["value", "valid"],
    )

    def create_runtime(self, spec: ComponentSpec) -> ComponentRuntime:
        default = spec.config.get("default")
        required = bool(spec.config.get("required", False))
        state = ValueState(value=default, valid=None if not required else bool(default))
        return ComponentRuntime(
            id=spec.id,
            use=spec.use,
            state={"value": state.model_dump()},
            output={"value": state.value, "valid": state.valid},
        )
