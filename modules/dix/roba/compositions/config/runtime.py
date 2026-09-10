from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Protocol, cast

from dix.core.composition import CompositionRuntimeContext


class StateApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Own one explicit local ROBA daemon configuration."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
        state: StateApi,
    ) -> None:
        self.context = context
        self.config = config
        self.state = state

    def get(self) -> dict[str, object]:
        """Return the complete ROBA daemon configuration."""
        value = self.state.require("get")()
        if not isinstance(value, dict):
            raise TypeError("local state get must return a dictionary")
        return cast(dict[str, object], value)

    def set(self, values: Mapping[str, object]) -> bool:
        """Validate and replace the complete ROBA daemon configuration."""
        result = self.state.require("set")(values)
        if type(result) is not bool:
            raise TypeError("local state set must return a boolean")
        return result

    def environment(self) -> dict[str, str]:
        """Build one explicit ROBA environment from the current local configuration."""
        environment = {key: value for key, value in os.environ.items() if not key.startswith("ROBA_")}
        values = self.get()
        environment["ROBA_RUNTIME_ROOT"] = _required_string(values, "runtime_root")
        environment["ROBA_LOGS_ROOT"] = _required_string(values, "logs_root")
        return environment


def _required_string(values: Mapping[str, object], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value:
        raise TypeError(f"ROBA configuration field '{name}' must be a non-empty string")
    return value
