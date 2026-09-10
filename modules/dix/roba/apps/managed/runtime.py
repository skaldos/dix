from __future__ import annotations

from collections.abc import Mapping

from dix.core.application import ApplicationApi, ApplicationRuntimeContext


class Runtime:
    """Compose raw ROBA start and DIX control attach with local ownership."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        daemon: ApplicationApi,
        control: ApplicationApi,
    ) -> None:
        self.context = context
        self.config = config
        self.daemon = daemon
        self.control = control

    def start(
        self,
        *,
        daemon_id: str = "default",
        runtime_root: str = "~/.roba/runtime",
        logs_root: str = "~/.roba/logs",
        timeout: float = 5.0,
    ) -> dict[str, object]:
        """Start one DIX-owned daemon and attach its control registry."""
        invocation = {
            "daemon_id": daemon_id,
            "runtime_root": runtime_root,
            "logs_root": logs_root,
            "timeout": timeout,
        }
        started = False
        try:
            creation = self.daemon.require("start")(**invocation)
            started = True
            control_locator = _required_locator(
                getattr(creation, "control_locator", None),
                "control_locator",
            )
            control_token = _required_string(
                getattr(creation, "control_token", None),
                "control_token",
            )
            result = self.control.require("bootstrap")(
                control_locator=control_locator,
                control_token=control_token,
                **invocation,
            )
            if not isinstance(result, dict):
                raise TypeError("ROBA control bootstrap must return a dictionary")
            return result
        except Exception as error:
            if not started:
                raise
            cleanup_errors: list[str] = []
            try:
                self.daemon.require("stop")(**invocation)
            except Exception as cleanup_error:
                cleanup_errors.append(f"daemon cleanup: {cleanup_error}")
            if cleanup_errors:
                raise RuntimeError(
                    f"{error}; cleanup failures: {' | '.join(cleanup_errors)}"
                ) from error
            raise


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty string")
    return value


def _required_locator(value: object, name: str) -> str:
    if value is None:
        raise TypeError(f"{name} must be a non-empty string")
    result = str(value)
    if not result:
        raise TypeError(f"{name} must be a non-empty string")
    return result
