from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from roba import daemon_status, start_daemon, stop_daemon

from dix.core.composition import CompositionRuntimeContext


class RobaConfigApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Adapt only ROBA's public daemon lifecycle API."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
        roba_config: RobaConfigApi,
    ) -> None:
        self.context = context
        self.config = config
        self.roba_config = roba_config

    def start(self) -> object:
        """Start one ROBA daemon from the current local configuration."""
        values = self._values()
        return start_daemon(
            self._daemon_id(values),
            timeout=self._timeout(values),
            env=self._environment(),
        )

    def get(self) -> dict[str, object]:
        """Return the complete configuration owned by this daemon composition."""
        values = self.roba_config.require("get")()
        if not isinstance(values, dict):
            raise TypeError("ROBA config get must return a dictionary")
        return values

    def set(self, values: Mapping[str, object]) -> bool:
        """Validate and replace the configuration owned by this daemon composition."""
        changed = self.roba_config.require("set")(values)
        if type(changed) is not bool:
            raise TypeError("ROBA config set must return a boolean")
        return changed

    def status(self) -> dict[str, object]:
        """Return status for the configured ROBA daemon."""
        values = self._values()
        return dict(
            daemon_status(
                daemon=f"id:{self._daemon_id(values)}",
                env=self._environment(),
            )
        )

    def stop(self) -> dict[str, object]:
        """Stop the configured ROBA daemon."""
        values = self._values()
        return dict(
            stop_daemon(
                daemon=f"id:{self._daemon_id(values)}",
                timeout=self._timeout(values),
                env=self._environment(),
            )
        )

    def _values(self) -> Mapping[str, object]:
        values = self.roba_config.require("get")()
        if not isinstance(values, Mapping):
            raise TypeError("ROBA config get must return a mapping")
        return values

    def _environment(self) -> Mapping[str, str]:
        environment = self.roba_config.require("environment")()
        if not isinstance(environment, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in environment.items()
        ):
            raise TypeError("ROBA config environment must return a string mapping")
        return environment

    @staticmethod
    def _daemon_id(values: Mapping[str, object]) -> str:
        value = values.get("daemon_id")
        if not isinstance(value, str) or not value:
            raise TypeError("ROBA config daemon_id must be a non-empty string")
        return value

    @staticmethod
    def _timeout(values: Mapping[str, object]) -> float:
        value = values.get("timeout")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("ROBA config timeout must be a number")
        return float(value)
