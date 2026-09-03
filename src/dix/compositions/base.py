from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol

from dix.core import ComponentRegistry


class CompositionError(Exception):
    """Base error for trusted composition registration and execution."""


class CompositionNotFound(CompositionError):
    """Raised when a trusted composition factory is not registered."""


class CompositionOperationNotFound(CompositionError):
    """Raised when a bound composition does not expose an operation."""


@dataclass(frozen=True)
class CompositionContext:
    components: ComponentRegistry
    base_dir: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_dir", self.base_dir.resolve())


CompositionOperationHandler = Callable[[Mapping[str, Any]], Any]


@dataclass(frozen=True)
class CompositionOperation:
    id: str
    handler: CompositionOperationHandler

    def __post_init__(self) -> None:
        operation_id = self.id.strip()
        if not operation_id:
            raise CompositionError("composition operation id must not be empty")
        if not callable(self.handler):
            raise CompositionError(f"composition operation '{operation_id}' is not callable")
        object.__setattr__(self, "id", operation_id)

    def invoke(self, parameters: Mapping[str, Any] | None = None) -> Any:
        return self.handler(MappingProxyType(dict(parameters or {})))


@dataclass(frozen=True)
class BoundComposition:
    id: str
    operations: Mapping[str, CompositionOperation]

    def __post_init__(self) -> None:
        composition_id = self.id.strip()
        if not composition_id:
            raise CompositionError("bound composition id must not be empty")
        operations: dict[str, CompositionOperation] = {}
        for raw_id, operation in self.operations.items():
            operation_id = raw_id.strip()
            if operation_id != operation.id:
                raise CompositionError(
                    f"operation key '{raw_id}' does not match operation id '{operation.id}'"
                )
            if operation_id in operations:
                raise CompositionError(f"duplicate composition operation: {operation_id}")
            operations[operation_id] = operation
        object.__setattr__(self, "id", composition_id)
        object.__setattr__(self, "operations", MappingProxyType(operations))

    def invoke(
        self,
        operation_id: str,
        parameters: Mapping[str, Any] | None = None,
    ) -> Any:
        try:
            operation = self.operations[operation_id]
        except KeyError as exc:
            raise CompositionOperationNotFound(
                f"composition '{self.id}' does not expose operation '{operation_id}'"
            ) from exc
        return operation.invoke(parameters)


class CompositionFactory(Protocol):
    composition_id: str

    def bind(
        self,
        context: CompositionContext,
        config: Mapping[str, Any],
    ) -> BoundComposition:
        """Bind one trusted composition instance to an explicit context."""
