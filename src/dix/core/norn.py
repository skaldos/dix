from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .element import ElementComponent, ElementIssue, ElementProcessor, ElementSpec

StrandHandler = Callable[[Any], Any]


class NornError(Exception):
    """Base error for strand definition, binding, and execution."""


class StrandDefinitionError(NornError):
    """Raised when a strand definition is structurally invalid."""


class StrandRegistrationError(NornError):
    """Raised when a strand or binding cannot be registered."""


class StrandNotFound(NornError):
    """Raised when a strand definition is unknown in this Norn instance."""


class StrandNotBound(NornError):
    """Raised when a known strand has no implementation in this Norn instance."""


class StrandValueError(NornError):
    """Base error for incompatible strand boundary values."""

    def __init__(
        self,
        message: str,
        *,
        strand_id: str,
        issues: tuple[ElementIssue, ...],
    ) -> None:
        super().__init__(message)
        self.strand_id = strand_id
        self.issues = issues


class StrandInputError(StrandValueError):
    """Raised when a value is incompatible with a strand input element."""


class StrandOutputError(StrandValueError):
    """Raised when a handler result is incompatible with a strand output element."""


class StrandExecutionError(NornError):
    """Raised when a bound strand handler fails."""

    def __init__(self, strand_id: str, handler_id: str) -> None:
        super().__init__(f"strand handler failed: strand='{strand_id}', handler='{handler_id}'")
        self.strand_id = strand_id
        self.handler_id = handler_id


@dataclass(frozen=True)
class StrandDefinition:
    id: str
    input_element: ElementSpec
    output_element: ElementSpec

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _strand_id(self.id))
        if not isinstance(self.input_element, ElementSpec):
            raise StrandDefinitionError("strand input_element must be an ElementSpec")
        if not isinstance(self.output_element, ElementSpec):
            raise StrandDefinitionError("strand output_element must be an ElementSpec")


@dataclass(frozen=True)
class RegisteredStrand:
    definition: StrandDefinition
    input_processor: ElementProcessor = field(repr=False)
    output_processor: ElementProcessor = field(repr=False)


@dataclass(frozen=True)
class StrandBinding:
    strand_id: str
    handler_id: str
    handler: StrandHandler = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "strand_id", _strand_id(self.strand_id))
        handler_id = self.handler_id.strip()
        if not handler_id:
            raise StrandRegistrationError("strand handler_id must not be empty")
        if not callable(self.handler):
            raise StrandRegistrationError("strand handler must be callable")
        object.__setattr__(self, "handler_id", handler_id)


@dataclass(frozen=True)
class StrandDescriptor:
    id: str
    input_element: ElementSpec
    output_element: ElementSpec
    bound: bool
    handler_id: str | None


class NornComponent:
    """Scope-local registry and invocation boundary for model-independent strands."""

    component_id = "norn"

    def __init__(self, element: ElementComponent) -> None:
        self.element = element
        self._registered: dict[str, RegisteredStrand] = {}
        self._bindings: dict[str, StrandBinding] = {}

    def register(self, definition: StrandDefinition) -> RegisteredStrand:
        if not isinstance(definition, StrandDefinition):
            raise StrandDefinitionError("strand definition must be a StrandDefinition")
        if definition.id in self._registered:
            raise StrandRegistrationError(f"strand is already registered: {definition.id}")

        input_processor = self.element.bind(definition.input_element)
        output_processor = self.element.bind(definition.output_element)
        registered = RegisteredStrand(
            definition=definition,
            input_processor=input_processor,
            output_processor=output_processor,
        )
        self._registered[definition.id] = registered
        return registered

    def bind(
        self,
        strand_id: str,
        *,
        handler_id: str,
        handler: StrandHandler,
    ) -> StrandBinding:
        normalized_id = _strand_id(strand_id)
        self._require_registered(normalized_id)
        if normalized_id in self._bindings:
            raise StrandRegistrationError(f"strand is already bound: {normalized_id}")
        binding = StrandBinding(
            strand_id=normalized_id,
            handler_id=handler_id,
            handler=handler,
        )
        self._bindings[normalized_id] = binding
        return binding

    def describe(self, strand_id: str) -> StrandDescriptor:
        registered = self._require_registered(_strand_id(strand_id))
        binding = self._bindings.get(registered.definition.id)
        return StrandDescriptor(
            id=registered.definition.id,
            input_element=registered.definition.input_element,
            output_element=registered.definition.output_element,
            bound=binding is not None,
            handler_id=None if binding is None else binding.handler_id,
        )

    def strands(self) -> tuple[StrandDescriptor, ...]:
        return tuple(self.describe(strand_id) for strand_id in sorted(self._registered))

    async def call(self, strand_id: str, value: Any) -> Any:
        normalized_id = _strand_id(strand_id)
        registered = self._require_registered(normalized_id)
        binding = self._bindings.get(normalized_id)
        if binding is None:
            raise StrandNotBound(f"strand is not bound: {normalized_id}")

        input_result = registered.input_processor.decode(value)
        if not input_result.compatible:
            raise StrandInputError(
                _value_error_message("input", normalized_id, input_result.issues),
                strand_id=normalized_id,
                issues=input_result.issues,
            )

        try:
            output = binding.handler(input_result.value)
            if inspect.isawaitable(output):
                output = await output
        except Exception as exc:
            raise StrandExecutionError(normalized_id, binding.handler_id) from exc

        output_result = registered.output_processor.decode(output)
        if not output_result.compatible:
            raise StrandOutputError(
                _value_error_message("output", normalized_id, output_result.issues),
                strand_id=normalized_id,
                issues=output_result.issues,
            )
        return output_result.value

    def _require_registered(self, strand_id: str) -> RegisteredStrand:
        try:
            return self._registered[strand_id]
        except KeyError as exc:
            raise StrandNotFound(f"strand is not registered: {strand_id}") from exc


def _strand_id(value: str) -> str:
    if not isinstance(value, str):
        raise StrandDefinitionError("strand id must be a string")
    normalized = value.strip()
    parts = normalized.split("/")
    if (
        len(parts) < 2
        or any(not part or part in {".", ".."} for part in parts)
        or any(character.isspace() for character in normalized)
    ):
        raise StrandDefinitionError(f"strand id must be namespaced: {value!r}")
    return normalized


def _value_error_message(
    boundary: str,
    strand_id: str,
    issues: tuple[ElementIssue, ...],
) -> str:
    details = "; ".join(issue.message for issue in issues) or "unknown incompatibility"
    return f"strand {boundary} is incompatible: strand='{strand_id}': {details}"
