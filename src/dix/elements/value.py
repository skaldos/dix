from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from dix.models import ElementContract, ElementFunction


class ValueState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any | None = None
    valid: bool | None = None
    error: str | None = None

    def set(self, value: Any) -> "ValueState":
        return self.model_copy(update={"value": value, "valid": True, "error": None})

    def clear(self) -> "ValueState":
        return self.model_copy(update={"value": None, "valid": None, "error": None})


VALUE_CONTRACT = ElementContract(
    id="value",
    description="Single headless value state.",
    state_fields=["value", "valid", "error"],
    functions=[
        ElementFunction(id="set", description="Set the current value."),
        ElementFunction(id="clear", description="Clear the current value."),
    ],
    events=["changed"],
)
