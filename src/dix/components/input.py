from __future__ import annotations

from typing import Any

from dix.elements.value import ValueState
from dix.models import ComponentDefinition, ComponentRuntime, ComponentSpec, InteractionContract

from .base import Component


class InputComponent(Component):
    definition = ComponentDefinition(
        id="input",
        description="Text-like input component backed by the headless value element.",
        elements=["value"],
        outputs=["value", "valid"],
        interaction=InteractionContract(
            role="value_input",
            capabilities=["set_value", "clear_value", "validation_state"],
            state_fields=["value.value", "value.valid", "value.error"],
            output_fields=["value", "valid"],
        ),
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

    def update_runtime(
        self, spec: ComponentSpec, runtime: ComponentRuntime, data: dict[str, Any]
    ) -> ComponentRuntime:
        state = ValueState.model_validate(runtime.state["value"]).set(data.get("value"))
        required = bool(spec.config.get("required", False))
        if required and (state.value is None or state.value == ""):
            state = state.model_copy(update={"valid": False, "error": "value is required"})
        return runtime.model_copy(
            update={
                "state": {"value": state.model_dump()},
                "output": {"value": state.value, "valid": state.valid},
            }
        )
