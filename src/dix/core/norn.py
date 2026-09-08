from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .datamodel import DatamodelComponent, ModelDefinition, ModelResult, RegisteredModel
from .element import (
    ElementBinding,
    ElementIssue,
    ElementProcessor,
    ElementResult,
    ElementSpec,
)

StrandHandler = Callable[[Any], Any]
MODEL_ELEMENT_TYPE = "model"


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


@dataclass(frozen=True)
class _ModelElementProcessor:
    datamodel: DatamodelComponent
    model: RegisteredModel

    def decode(self, raw: Any) -> ElementResult:
        if not isinstance(raw, Mapping):
            return ElementResult(
                value=None,
                compatible=False,
                issues=(
                    ElementIssue(
                        code="incompatible_model_value",
                        message=f"expected model mapping, got {type(raw).__name__}",
                        details={
                            "model": self.model.definition.name,
                            "received": type(raw).__name__,
                        },
                    ),
                ),
            )
        result = self.datamodel.instantiate(self.model, raw)
        return ElementResult(
            value=result.values if result.compatible else None,
            compatible=result.compatible,
            issues=_model_issues(result),
        )


class _ModelElementHandler:
    handler_id = "norn.model"

    def __init__(self, datamodel: DatamodelComponent) -> None:
        self.datamodel = datamodel

    def bind(
        self,
        spec: ElementSpec,
        delegate: ElementProcessor | None,
    ) -> ElementProcessor:
        if delegate is not None:
            raise StrandDefinitionError("Norn model element cannot wrap a delegate")
        definition, elements = _model_element_contract(spec)
        registered = self.datamodel.register_model(definition, elements=elements)
        return _ModelElementProcessor(self.datamodel, registered)


class NornComponent:
    """Scope-local registry and invocation boundary for model-independent strands."""

    component_id = "norn"

    def __init__(self, datamodel: DatamodelComponent) -> None:
        self.datamodel = datamodel
        self.element = datamodel.element
        self._model_binding = ElementBinding(
            type_name=MODEL_ELEMENT_TYPE,
            handler_id=_ModelElementHandler.handler_id,
            handler=_ModelElementHandler(datamodel),
            mode="define",
        )
        self._registered: dict[str, RegisteredStrand] = {}
        self._bindings: dict[tuple[str, str], StrandBinding] = {}

    def register(self, definition: StrandDefinition) -> RegisteredStrand:
        if not isinstance(definition, StrandDefinition):
            raise StrandDefinitionError("strand definition must be a StrandDefinition")
        if definition.id in self._registered:
            raise StrandRegistrationError(f"strand is already registered: {definition.id}")

        element_scope = self.element.create_extension_scope(
            (self._model_binding,),
            parent=self.datamodel.default_element_scope,
        )
        input_processor = self.element.bind(definition.input_element, element_scope)
        output_processor = self.element.bind(definition.output_element, element_scope)
        registered = RegisteredStrand(
            definition=definition,
            input_processor=input_processor,
            output_processor=output_processor,
        )
        self._registered[definition.id] = registered
        return registered

    def ensure_registered(self, definition: StrandDefinition) -> RegisteredStrand:
        """Return an identical registration or create it without masking conflicts."""
        existing = self._registered.get(definition.id)
        if existing is None:
            return self.register(definition)
        if existing.definition != definition:
            raise StrandRegistrationError(
                f"strand is already registered with a different definition: {definition.id}"
            )
        return existing

    def bind(
        self,
        strand_id: str,
        *,
        handler_id: str,
        handler: StrandHandler,
    ) -> StrandBinding:
        normalized_id = _strand_id(strand_id)
        self._require_registered(normalized_id)
        key = (normalized_id, handler_id)
        if key in self._bindings:
            raise StrandRegistrationError(
                f"strand handler is already bound: {normalized_id}/{handler_id}"
            )
        binding = StrandBinding(
            strand_id=normalized_id,
            handler_id=handler_id,
            handler=handler,
        )
        self._bindings[key] = binding
        return binding

    def describe(self, strand_id: str) -> StrandDescriptor:
        registered = self._require_registered(_strand_id(strand_id))
        bindings = self._strand_bindings(registered.definition.id)
        binding = bindings[0] if len(bindings) == 1 else None
        return StrandDescriptor(
            id=registered.definition.id,
            input_element=registered.definition.input_element,
            output_element=registered.definition.output_element,
            bound=bool(bindings),
            handler_id=None if binding is None else binding.handler_id,
        )

    def strands(self) -> tuple[StrandDescriptor, ...]:
        return tuple(self.describe(strand_id) for strand_id in sorted(self._registered))

    async def call(
        self,
        strand_id: str,
        value: Any,
        *,
        handler_id: str | None = None,
    ) -> Any:
        normalized_id = _strand_id(strand_id)
        registered = self._require_registered(normalized_id)
        bindings = self._strand_bindings(normalized_id)
        if handler_id is None:
            if not bindings:
                raise StrandNotBound(f"strand is not bound: {normalized_id}")
            if len(bindings) != 1:
                raise StrandNotBound(
                    f"strand has multiple bindings; handler_id is required: {normalized_id}"
                )
            binding = bindings[0]
        else:
            binding = self._bindings.get((normalized_id, handler_id))
            if binding is None:
                raise StrandNotBound(
                    f"strand handler is not bound: {normalized_id}/{handler_id}"
                )

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

    def _strand_bindings(self, strand_id: str) -> tuple[StrandBinding, ...]:
        return tuple(
            binding
            for (candidate_id, _), binding in sorted(self._bindings.items())
            if candidate_id == strand_id
        )

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


def model_element(
    definition: ModelDefinition,
    *,
    elements: tuple[ElementBinding, ...] = (),
) -> ElementSpec:
    """Represent one immutable model definition as a local Norn boundary element."""
    if not isinstance(definition, ModelDefinition):
        raise StrandDefinitionError("model element definition must be a ModelDefinition")
    if not isinstance(elements, tuple) or not all(
        isinstance(binding, ElementBinding) for binding in elements
    ):
        raise StrandDefinitionError("model element bindings must be a tuple of ElementBinding")
    return ElementSpec(
        MODEL_ELEMENT_TYPE,
        {
            "definition": definition,
            "elements": elements,
        },
    )


def model_definition(element: ElementSpec) -> ModelDefinition:
    """Return the model definition carried by a Norn model boundary element."""
    definition, _ = _model_element_contract(element)
    return definition


def _model_element_contract(
    spec: ElementSpec,
) -> tuple[ModelDefinition, tuple[ElementBinding, ...]]:
    if spec.type != MODEL_ELEMENT_TYPE:
        raise StrandDefinitionError(f"expected a '{MODEL_ELEMENT_TYPE}' element")
    if set(spec.config) != {"definition", "elements"}:
        raise StrandDefinitionError(
            "model element config must contain exactly 'definition' and 'elements'"
        )
    definition = spec.config["definition"]
    elements = spec.config["elements"]
    if not isinstance(definition, ModelDefinition):
        raise StrandDefinitionError("model element definition must be a ModelDefinition")
    if not isinstance(elements, tuple) or not all(
        isinstance(binding, ElementBinding) for binding in elements
    ):
        raise StrandDefinitionError("model element bindings must be a tuple of ElementBinding")
    return definition, elements


def _model_issues(result: ModelResult) -> tuple[ElementIssue, ...]:
    return tuple(
        ElementIssue(
            code=issue.code,
            message=(
                issue.message
                if issue.field is None
                else f"model field '{issue.field}': {issue.message}"
            ),
            details={"field": issue.field, **dict(issue.details)},
        )
        for issue in result.issues
    )


def _value_error_message(
    boundary: str,
    strand_id: str,
    issues: tuple[ElementIssue, ...],
) -> str:
    details = "; ".join(issue.message for issue in issues) or "unknown incompatibility"
    return f"strand {boundary} is incompatible: strand='{strand_id}': {details}"
