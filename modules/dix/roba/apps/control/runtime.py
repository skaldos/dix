from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from dix.core.application import ApplicationRuntimeContext


class ControlApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Expose the control registry with explicit configuration per invocation."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        control: ControlApi,
    ) -> None:
        self.context = context
        self.config = config
        self.control = control

    def bootstrap(
        self,
        *,
        control_locator: str,
        control_token: str,
        daemon_id: str = "default",
        runtime_root: str = "~/.roba/runtime",
        logs_root: str = "~/.roba/logs",
        timeout: float = 5.0,
    ) -> object:
        """Attach to a running ROBA daemon and create the DIX control registry."""
        self._set_config(daemon_id, runtime_root, logs_root, timeout)
        return self.control.require("bootstrap")(
            control_locator=control_locator,
            control_token=control_token,
        )

    def control_credentials(
        self,
        *,
        daemon_id: str = "default",
        runtime_root: str = "~/.roba/runtime",
        logs_root: str = "~/.roba/logs",
        timeout: float = 5.0,
    ) -> dict[str, object]:
        """Read DIX control credentials through the root socket."""
        self._set_config(daemon_id, runtime_root, logs_root, timeout)
        value = self.control.require("control_credentials")()
        if not isinstance(value, dict):
            raise TypeError("control credentials must return a dictionary")
        return value

    def create_context(
        self,
        *,
        context_id: str,
        name: str = "",
        daemon_id: str = "default",
        runtime_root: str = "~/.roba/runtime",
        logs_root: str = "~/.roba/logs",
        timeout: float = 5.0,
    ) -> dict[str, object]:
        """Create one managed context and its scoped manager socket."""
        self._set_config(daemon_id, runtime_root, logs_root, timeout)
        value = self.control.require("create_context")(context_id, name)
        if not isinstance(value, dict):
            raise TypeError("created context must return a dictionary")
        return value

    def context_credentials(
        self,
        *,
        context_id: str,
        daemon_id: str = "default",
        runtime_root: str = "~/.roba/runtime",
        logs_root: str = "~/.roba/logs",
        timeout: float = 5.0,
    ) -> dict[str, object]:
        """Read one managed context owner through its manager socket."""
        self._set_config(daemon_id, runtime_root, logs_root, timeout)
        value = self.control.require("context_credentials")(context_id)
        if not isinstance(value, dict):
            raise TypeError("context credentials must return a dictionary")
        return value

    def _set_config(
        self,
        daemon_id: str,
        runtime_root: str,
        logs_root: str,
        timeout: float,
    ) -> None:
        changed = self.control.require("set")(
            {
                "daemon_id": daemon_id,
                "runtime_root": runtime_root,
                "logs_root": logs_root,
                "timeout": timeout,
            }
        )
        if type(changed) is not bool:
            raise TypeError("ROBA control config set must return a boolean")
