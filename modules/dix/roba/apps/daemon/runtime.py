from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from dix.core.application import ApplicationRuntimeContext


class DaemonApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Expose ROBA daemon lifecycle with explicit invocation-local configuration."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        daemon: DaemonApi,
    ) -> None:
        self.context = context
        self.config = config
        self.daemon = daemon

    def start(
        self,
        *,
        daemon_id: str = "default",
        runtime_root: str = "~/.roba/runtime",
        logs_root: str = "~/.roba/logs",
        timeout: float = 5.0,
    ) -> object:
        """Set explicit ROBA configuration and start one daemon."""
        self._set_config(daemon_id, runtime_root, logs_root, timeout)
        return self.daemon.require("start")()

    def status(
        self,
        *,
        daemon_id: str = "default",
        runtime_root: str = "~/.roba/runtime",
        logs_root: str = "~/.roba/logs",
        timeout: float = 5.0,
    ) -> dict[str, object]:
        """Set explicit ROBA configuration and return daemon status."""
        self._set_config(daemon_id, runtime_root, logs_root, timeout)
        value = self.daemon.require("status")()
        if not isinstance(value, dict):
            raise TypeError("ROBA daemon status must return a dictionary")
        return value

    def stop(
        self,
        *,
        daemon_id: str = "default",
        runtime_root: str = "~/.roba/runtime",
        logs_root: str = "~/.roba/logs",
        timeout: float = 5.0,
    ) -> dict[str, object]:
        """Set explicit ROBA configuration and stop one daemon."""
        self._set_config(daemon_id, runtime_root, logs_root, timeout)
        value = self.daemon.require("stop")()
        if not isinstance(value, dict):
            raise TypeError("ROBA daemon stop must return a dictionary")
        return value

    def _set_config(
        self,
        daemon_id: str,
        runtime_root: str,
        logs_root: str,
        timeout: float,
    ) -> None:
        changed = self.daemon.require("set")(
            {
                "daemon_id": daemon_id,
                "runtime_root": runtime_root,
                "logs_root": logs_root,
                "timeout": timeout,
            }
        )
        if type(changed) is not bool:
            raise TypeError("ROBA daemon config set must return a boolean")
