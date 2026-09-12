from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from dix.core.application import ApplicationRuntimeContext


class ApplicationApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


ROBA_INVOCATION: Mapping[str, object] = {
    "daemon_id": "default",
    "runtime_root": "~/.roba/runtime",
    "logs_root": "~/.roba/logs",
    "timeout": 5.0,
}
SWAY_CONTEXT_ID = "sway"


class Runtime:
    """Own the explicit lifecycle of one Sway-specific ROBA runtime."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        managed: ApplicationApi,
        control: ApplicationApi,
        daemon: ApplicationApi,
    ) -> None:
        self.context = context
        self.config = config
        self.managed = managed
        self.control = control
        self.daemon = daemon

    def start(self) -> dict[str, object]:
        """Start the Sway daemon, control registry, and fixed Sway context."""
        started = False
        try:
            self.managed.require("start")(**ROBA_INVOCATION)
            started = True
            self.control.require("create_context")(
                context_id=SWAY_CONTEXT_ID,
                **ROBA_INVOCATION,
            )
            return self._status()
        except Exception as error:
            if not started:
                raise
            try:
                self.daemon.require("stop")(**ROBA_INVOCATION)
            except Exception as cleanup_error:
                raise RuntimeError(
                    f"Sway runtime start failed: {error}; "
                    f"cleanup failed: {cleanup_error}"
                ) from error
            raise

    def status(self) -> dict[str, object]:
        """Read the complete Sway runtime without mutating or returning credentials."""
        return self._status()

    def stop(self) -> dict[str, object]:
        """Stop the owned daemon and its complete ephemeral runtime generation."""
        value = self.daemon.require("stop")(**ROBA_INVOCATION)
        return _required_mapping(value, "ROBA daemon stop")

    def _status(self) -> dict[str, object]:
        daemon_status = _required_mapping(
            self.daemon.require("status")(**ROBA_INVOCATION),
            "ROBA daemon status",
        )
        _required_mapping(
            self.control.require("control_credentials")(**ROBA_INVOCATION),
            "ROBA control credentials",
        )
        _required_mapping(
            self.control.require("context_credentials")(
                context_id=SWAY_CONTEXT_ID,
                **ROBA_INVOCATION,
            ),
            "ROBA Sway context credentials",
        )
        return {
            "daemon": daemon_status,
            "control_ready": True,
            "context_id": SWAY_CONTEXT_ID,
            "context_ready": True,
        }


def _required_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must return a mapping")
    return dict(value)
