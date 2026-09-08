from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from pydantic import ValidationError

from dix.core.application import ApplicationRuntimeContext


class StatesApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Pressure-test two owner-controlled state compositions through public functions only."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        states: StatesApi,
    ) -> None:
        self.context = context
        self.config = config
        self.states = states

    def snapshot(self) -> dict[str, object]:
        """Return the two independent owner states and local reaction count."""
        return {
            "base": self.states.require("get_base")(),
            "reactive": self.states.require("get_reactive")(),
            "reactions": self.states.require("reaction_count")(),
        }

    def pressure(self) -> dict[str, object]:
        """Exercise explicit local state composition boundaries."""
        initial = self.snapshot()
        detached = self.states.require("get_base")()
        detached["metadata"]["tags"].append("caller-only")

        base_changed = self.states.require("set_base")(
            {"label": "updated", "count": "2", "metadata": {"tags": ["updated"]}}
        )
        same_changed = self.states.require("set_reactive")(
            {"mode": "idle", "enabled": True}
        )
        reactive_changed = self.states.require("set_reactive")(
            {"mode": "active", "enabled": False}
        )
        try:
            self.states.require("set_reactive")(
                {"mode": "broken", "enabled": "not-a-boolean"}
            )
        except ValidationError as exc:
            invalid = {
                "type": exc.errors()[0]["type"],
                "location": list(exc.errors()[0]["loc"]),
            }
        else:
            raise AssertionError("invalid reactive state unexpectedly passed validation")

        return {
            "initial": initial,
            "detached_base": self.states.require("get_base")(),
            "base_changed": base_changed,
            "same_changed": same_changed,
            "reactive_changed": reactive_changed,
            "invalid": invalid,
            "final": self.snapshot(),
        }
