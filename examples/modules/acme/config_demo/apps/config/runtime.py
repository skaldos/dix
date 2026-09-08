from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from pydantic import BaseModel, ValidationError

from dix.core.application import ApplicationRuntimeContext


class ConfigModelApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


CONFIG_MODEL_SPEC: dict[str, object] = {
    "name": "DemoConfig",
    "fields": {
        "service": {
            "type": "string",
            "help": "Name of the configured service.",
        },
        "workers": {"type": "integer", "default": 1},
        "enabled": {"type": "boolean", "default": True},
        "renderer": {
            "type": "model",
            "name": "RendererConfig",
            "fields": {
                "theme": {"type": "string"},
                "upper": {"type": "boolean", "default": False},
            },
        },
    },
}


class Runtime:
    """Application-owned use of one local declarative configuration model."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        config_model: ConfigModelApi,
    ) -> None:
        self.context = context
        self.config = config
        resolve = config_model.require("resolve")
        model = resolve(CONFIG_MODEL_SPEC)
        if not isinstance(model, type) or not issubclass(model, BaseModel):
            raise TypeError("config model resolver must return a Pydantic model type")
        self.model = model

    def validate(self, values: Mapping[str, object]) -> dict[str, object]:
        """Validate owner-provided values with the application-owned config model."""
        return self.model.model_validate(values).model_dump()

    def pressure(self) -> dict[str, object]:
        """Exercise valid and invalid owner-controlled config values."""
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
            raise AssertionError("invalid config values unexpectedly passed validation")
        return {
            "first": first,
            "second": second,
            "invalid": invalid,
            "help": self.model.model_fields["service"].description,
        }
