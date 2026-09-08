from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from pydantic import BaseModel, ValidationError

from dix.core.application import ApplicationRuntimeContext


class StateModelApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


STATE_MODEL_SPEC: dict[str, object] = {
    "name": "DemoState",
    "fields": {
        "service": {
            "type": "string",
            "help": "Name of the configured service.",
        },
        "workers": {"type": "integer", "default": 1},
        "enabled": {"type": "boolean", "default": True},
        "renderer": {
            "type": "model",
            "name": "RendererState",
            "fields": {
                "theme": {"type": "string"},
                "upper": {"type": "boolean", "default": False},
            },
        },
    },
}


class Runtime:
    """Application-owned use of one local declarative state model."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        state_models: StateModelApi,
    ) -> None:
        self.context = context
        self.config = config
        resolve = state_models.require("resolve")
        model = resolve(STATE_MODEL_SPEC)
        if not isinstance(model, type) or not issubclass(model, BaseModel):
            raise TypeError("state model resolver must return a Pydantic model type")
        self.model = model

    def validate(self, values: Mapping[str, object]) -> dict[str, object]:
        """Validate owner-provided values with the application-owned state model."""
        return self.model.model_validate(values).model_dump()

    def pressure(self) -> dict[str, object]:
        """Exercise valid and invalid owner-controlled state values."""
        first = self.validate(
            {
                "service": "alpha",
                "renderer": {"theme": "dark"},
            }
        )
        second = self.validate(
            {
                "service": "beta",
                "workers": 4,
                "enabled": False,
                "renderer": {"theme": "light", "upper": True},
            }
        )
        try:
            self.validate(
                {
                    "service": "broken",
                    "workers": "not-an-integer",
                    "renderer": {"theme": "dark"},
                }
            )
        except ValidationError as exc:
            invalid = {
                "error_type": exc.errors()[0]["type"],
                "location": list(exc.errors()[0]["loc"]),
            }
        else:
            raise AssertionError("invalid state values unexpectedly passed validation")
        return {
            "first": first,
            "second": second,
            "invalid": invalid,
            "help": self.model.model_fields["service"].description,
        }
