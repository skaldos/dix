from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from roba import (
    ContextApi,
    ControlApi,
    ResourceNotFound,
    RobaClient,
    create_context,
    principal_socket,
)

from dix.core.composition import CompositionRuntimeContext

CONTROL_CONTEXT_ID = "dix.control"
ROOT_SOCKET_ID = "admin"


class ConfigApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Own the explicit DIX capability registry for one ROBA daemon."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
        roba_config: ConfigApi,
    ) -> None:
        self.context = context
        self.config = config
        self.roba_config = roba_config

    def get(self) -> dict[str, object]:
        """Return the daemon configuration owned by this registry."""
        value = self.roba_config.require("get")()
        if not isinstance(value, dict):
            raise TypeError("ROBA daemon config get must return a dictionary")
        return value

    def set(self, values: Mapping[str, object]) -> bool:
        """Replace the daemon configuration owned by this registry."""
        result = self.roba_config.require("set")(values)
        if type(result) is not bool:
            raise TypeError("ROBA daemon config set must return a boolean")
        return result

    def bootstrap(
        self,
        *,
        control_locator: str,
        control_token: str,
    ) -> dict[str, object]:
        """Attach to a running daemon and create the DIX control context and root socket."""
        values = self._values()
        daemon_id = self._daemon_id(values)
        environment = self._environment()
        control_locator = _required_string(control_locator, "control_locator")
        control_token = _required_string(control_token, "control_token")
        context = None
        root_owner: ContextApi | None = None
        root_socket_attempted = False
        try:
            context = create_context(
                context_id=CONTROL_CONTEXT_ID,
                name=CONTROL_CONTEXT_ID,
                control=control_locator,
                control_token=control_token,
                timeout=self._timeout(values),
                env=environment,
            )
            root_owner = _context_owner(
                context.socket,
                context.owner_token,
                timeout=self._timeout(values),
            )
            root_owner.set(
                "control_locator",
                control_locator,
            )
            root_owner.set("control_token", control_token)
            root_owner.set("owner_token", context.owner_token)
            root_socket_attempted = True
            root_socket = root_owner.socket_create(
                socket_id=ROOT_SOCKET_ID,
                name=ROOT_SOCKET_ID,
                read=["context"],
            )
        # Roll back every partially published external resource for any client failure.
        except Exception as error:  # noqa: BLE001
            cleanup_errors: list[str] = []
            if root_owner is not None and root_socket_attempted:
                try:
                    root_owner.socket_delete(socket_id=ROOT_SOCKET_ID)
                except ResourceNotFound:
                    pass
                except Exception as cleanup_error:  # noqa: BLE001
                    cleanup_errors.append(f"root socket cleanup: {cleanup_error}")
            if context is not None:
                try:
                    _control_client(
                        control_locator,
                        control_token,
                        environment,
                        self._timeout(values),
                    ).context_delete(context_id=CONTROL_CONTEXT_ID)
                except Exception as cleanup_error:  # noqa: BLE001
                    cleanup_errors.append(f"control context cleanup: {cleanup_error}")
            _raise_with_cleanup(error, cleanup_errors)
        assert context is not None
        assert root_socket is not None
        return {
            "daemon_id": daemon_id,
            "control_locator": control_locator,
            "control_context": CONTROL_CONTEXT_ID,
            "control_context_locator": str(context.direct_locator),
            "control_owner_token": context.owner_token,
            "root_socket": str(root_socket["socket"]),
            "root_socket_id": ROOT_SOCKET_ID,
            "control_token": control_token,
        }

    def control_credentials(self) -> dict[str, object]:
        """Read root credentials through the tokenless administrative socket."""
        values = self._values()
        environment = self._environment()
        root = _root_socket_client(
            self._daemon_id(values),
            environment,
            self._timeout(values),
        )
        return {
            "control_locator": _state_string(root.get("control_locator"), "control_locator"),
            "control_token": _state_string(root.get("control_token"), "control_token"),
            "owner_token": _state_string(root.get("owner_token"), "owner_token"),
        }

    def create_context(self, context_id: str, name: str = "") -> dict[str, object]:
        """Create one managed context and its registry instance and manager socket."""
        values = self._values()
        environment = self._environment()
        credentials = self.control_credentials()
        control_locator = _state_string(credentials["control_locator"], "control_locator")
        control_token = _state_string(credentials["control_token"], "control_token")
        dix_owner = _state_string(credentials["owner_token"], "owner_token")
        context = create_context(
            context_id=context_id,
            name=name or context_id,
            control=control_locator,
            control_token=control_token,
            timeout=self._timeout(values),
            env=environment,
        )
        registry_owner = _context_owner_from_id(
            CONTROL_CONTEXT_ID,
            dix_owner,
            control_locator,
            environment,
            self._timeout(values),
        )
        instance_created = False
        socket_attempted = False
        try:
            registry_owner.instance_create(
                instance_id=context_id,
                name=context_id,
                state={
                    "context_locator": str(context.direct_locator),
                    "owner_token": context.owner_token,
                },
            )
            instance_created = True
            socket_attempted = True
            socket_record = registry_owner.socket_create(
                socket_id=context_id,
                name=context_id,
                read=[f"instance:{context_id}"],
            )
        # Context creation spans several external calls and therefore owns broad rollback.
        except Exception as error:  # noqa: BLE001
            cleanup_errors: list[str] = []
            if socket_attempted:
                try:
                    registry_owner.socket_delete(socket_id=context_id)
                except ResourceNotFound:
                    pass
                except Exception as cleanup_error:  # noqa: BLE001
                    cleanup_errors.append(f"manager socket cleanup: {cleanup_error}")
            if instance_created:
                try:
                    registry_owner.instance_delete(instance_id=context_id)
                except Exception as cleanup_error:  # noqa: BLE001
                    cleanup_errors.append(f"registry instance cleanup: {cleanup_error}")
            try:
                _control_client(
                    control_locator,
                    control_token,
                    environment,
                    self._timeout(values),
                ).context_delete(context_id=context_id)
            except Exception as cleanup_error:  # noqa: BLE001
                cleanup_errors.append(f"target context cleanup: {cleanup_error}")
            _raise_with_cleanup(error, cleanup_errors)
        assert socket_record is not None
        return {
            "context_id": context.context_id,
            "context_locator": str(context.direct_locator),
            "owner_token": context.owner_token,
            "manager_socket": str(socket_record["socket"]),
            "manager_socket_id": context_id,
        }

    def context_credentials(self, context_id: str) -> dict[str, object]:
        """Read one managed context credential through its scoped manager socket."""
        values = self._values()
        environment = self._environment()
        manager = _manager_socket_client(
            self._daemon_id(values),
            context_id,
            environment,
            self._timeout(values),
        )
        return {
            "context_locator": _state_string(
                manager.get("context_locator"), "context_locator"
            ),
            "owner_token": _state_string(manager.get("owner_token"), "owner_token"),
        }

    def _values(self) -> Mapping[str, object]:
        values = self.roba_config.require("get")()
        if not isinstance(values, Mapping):
            raise TypeError("ROBA daemon config must return a mapping")
        return values

    def _environment(self) -> Mapping[str, str]:
        environment = self.roba_config.require("environment")()
        if not isinstance(environment, Mapping):
            raise TypeError("ROBA config environment must return a mapping")
        return {
            key: value
            for key, value in environment.items()
            if isinstance(key, str) and isinstance(value, str)
        }

    def _daemon_id(self, values: Mapping[str, object]) -> str:
        return _required_string(values.get("daemon_id"), "daemon_id")

    def _timeout(self, values: Mapping[str, object]) -> float:
        value = values.get("timeout")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("ROBA config timeout must be a number")
        return float(value)


def _context_owner(socket: Path, token: str, *, timeout: float) -> ContextApi:
    return RobaClient(timeout=timeout).context(
        locator=f"unix:{socket}",
        token=token,
    )


def _context_owner_from_id(
    context_id: str,
    token: str,
    control_locator: str,
    environment: Mapping[str, str],
    timeout: float,
) -> ContextApi:
    return RobaClient(env=environment, timeout=timeout).context(
        locator=f"id:{context_id}",
        control=control_locator,
        token=token,
    )


def _control_client(
    locator: str,
    token: str,
    environment: Mapping[str, str],
    timeout: float,
) -> ControlApi:
    return RobaClient(env=environment, timeout=timeout).control(
        locator=locator,
        token=token,
    )


def _root_socket_client(
    daemon_id: str,
    environment: Mapping[str, str],
    timeout: float,
) -> ContextApi:
    socket = principal_socket(
        daemon_id,
        CONTROL_CONTEXT_ID,
        ROOT_SOCKET_ID,
        environment,
    )
    return RobaClient(env=environment, timeout=timeout).context(
        locator=f"unix:{socket}",
        token=None,
    )


def _manager_socket_client(
    daemon_id: str,
    context_id: str,
    environment: Mapping[str, str],
    timeout: float,
) -> ContextApi:
    socket = principal_socket(
        daemon_id,
        CONTROL_CONTEXT_ID,
        context_id,
        environment,
    )
    return RobaClient(env=environment, timeout=timeout).context(
        locator=f"unix:{socket}",
        scope=f"id:{context_id}",
        token=None,
    )


def _state_string(value: object, name: str) -> str:
    return _required_string(value, name)


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty string")
    return value


def _raise_with_cleanup(error: Exception, cleanup_errors: list[str]) -> None:
    if cleanup_errors:
        raise RuntimeError(
            f"{error}; cleanup failures: {' | '.join(cleanup_errors)}"
        ) from error
    raise error
