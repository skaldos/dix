from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from .runtime import CompositionApi, CompositionRuntimeError


class CompositionOwnerBindingError(RuntimeError):
    """Raised when an immediate-owner binding cannot be resolved safely."""


@dataclass(frozen=True)
class _BindingRequest:
    kind: Literal["dependency", "function"]
    name: str
    function_id: str
    target: _DeferredCallable


class _DeferredCallable:
    """Callable placeholder finalized exactly once during staged graph construction."""

    def __init__(self, description: str) -> None:
        self._description = description
        self._bound: Callable[..., object] | None = None

    def bind(self, function: Callable[..., object]) -> None:
        if self._bound is not None:
            raise CompositionOwnerBindingError(
                f"composition owner binding is already finalized: {self._description}"
            )
        self._bound = function

    def __call__(self, *args: object, **kwargs: object) -> object:
        if self._bound is None:
            raise CompositionOwnerBindingError(
                f"composition owner binding is not finalized: {self._description}"
            )
        return self._bound(*args, **kwargs)


class CompositionOwnerComponent:
    """Request callable bindings from one composition's immediate owner."""

    component_id = "composition_owner"

    def __init__(self) -> None:
        self._target: _CompositionOwnerTarget | None = None
        self._requests: list[_BindingRequest] = []

    def bind_dependency(
        self,
        alias: str,
        function_id: str,
    ) -> Callable[..., object]:
        """Bind one exposed function from an immediate-owner dependency alias."""
        target = self._require_target()
        request = _BindingRequest(
            kind="dependency",
            name=_require_identifier(alias, label="composition dependency alias"),
            function_id=_require_identifier(function_id, label="composition function id"),
            target=_DeferredCallable(f"dependency {alias}.{function_id}"),
        )
        self._requests.append(request)
        target.register(self)
        return request.target

    def bind_function(self, function_id: str) -> Callable[..., object]:
        """Bind one exposed function from the immediate owner's effective API."""
        target = self._require_target()
        normalized = _require_identifier(function_id, label="composition function id")
        request = _BindingRequest(
            kind="function",
            name=normalized,
            function_id=normalized,
            target=_DeferredCallable(f"owner function {normalized}"),
        )
        self._requests.append(request)
        target.register(self)
        return request.target

    def _attach(self, target: _CompositionOwnerTarget) -> None:
        if self._target is not None:
            raise CompositionOwnerBindingError("composition owner capability is already attached")
        self._target = target

    def _require_target(self) -> _CompositionOwnerTarget:
        if self._target is None:
            raise CompositionOwnerBindingError(
                "composition owner capability requires an immediate composition owner"
            )
        return self._target

    def _prepare_bindings(
        self,
        dependencies: Mapping[str, CompositionApi],
        owner_api: CompositionApi,
    ) -> tuple[tuple[_DeferredCallable, Callable[..., object]], ...]:
        prepared: list[tuple[_DeferredCallable, Callable[..., object]]] = []
        for request in self._requests:
            if request.kind == "dependency":
                try:
                    api = dependencies[request.name]
                except KeyError as exc:
                    raise CompositionOwnerBindingError(
                        "immediate owner does not declare composition dependency alias: "
                        f"{request.name}"
                    ) from exc
            else:
                api = owner_api
            try:
                descriptor = api.describe(request.function_id)
                function = api.require(request.function_id)
            except CompositionRuntimeError as exc:
                if request.kind == "dependency":
                    target = f"dependency {request.name}.{request.function_id}"
                else:
                    target = f"owner function {request.function_id}"
                raise CompositionOwnerBindingError(
                    f"immediate owner binding refers to undeclared {target}"
                ) from exc
            if descriptor.is_async:
                if request.kind == "dependency":
                    target = f"dependency {request.name}.{request.function_id}"
                else:
                    target = f"owner function {request.function_id}"
                raise CompositionOwnerBindingError(
                    f"immediate owner binding must be synchronous: {target}"
                )
            prepared.append((request.target, function))
        return tuple(prepared)


class _CompositionOwnerTarget:
    """Private staging target shared only by the direct children of one owner."""

    def __init__(self) -> None:
        self._capabilities: list[CompositionOwnerComponent] = []

    def register(self, capability: CompositionOwnerComponent) -> None:
        if capability not in self._capabilities:
            self._capabilities.append(capability)

    def finalize(
        self,
        dependencies: Mapping[str, CompositionApi],
        owner_api: CompositionApi,
    ) -> None:
        prepared = tuple(
            binding
            for capability in self._capabilities
            for binding in capability._prepare_bindings(dependencies, owner_api)
        )
        for target, function in prepared:
            target.bind(function)


def _require_identifier(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.isidentifier():
        raise CompositionOwnerBindingError(f"{label} must be a flat identifier: {value!r}")
    return value


__all__ = [
    "CompositionOwnerBindingError",
    "CompositionOwnerComponent",
]
