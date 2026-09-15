from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4

from .element import (
    ElementBinding,
    ElementComponent,
    ElementProcessor,
    ElementScope,
    ElementSpec,
    ElementTypeDescriptor,
)


class DatamodelError(Exception):
    """Raised when a model cannot be defined, registered, or instantiated."""


class ModelNotFound(DatamodelError):
    """Raised when a model registration UID is unknown."""


def _immutable_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class ModelDefinition:
    uid: UUID
    name: str
    schema: Mapping[str, ElementSpec]
    version: str | None = None

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise DatamodelError("model name must not be empty")
        if self.version is not None and not self.version.strip():
            raise DatamodelError("model version must not be empty")
        schema: dict[str, ElementSpec] = {}
        for raw_name, spec in self.schema.items():
            field_name = raw_name.strip()
            if not field_name:
                raise DatamodelError("model field name must not be empty")
            if field_name in schema:
                raise DatamodelError(f"duplicate model field: {field_name}")
            if not isinstance(spec, ElementSpec):
                raise DatamodelError(f"model field '{field_name}' must use ElementSpec")
            schema[field_name] = spec
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "schema", MappingProxyType(schema))


@dataclass(frozen=True)
class RegisteredModel:
    uid: UUID
    definition: ModelDefinition
    element_scope: ElementScope
    processors: Mapping[str, ElementProcessor] = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "processors", MappingProxyType(dict(self.processors)))


@dataclass(frozen=True)
class RegisteredModelDescriptor:
    uid: UUID
    definition_uid: UUID
    name: str
    version: str | None
    elements: tuple[ElementTypeDescriptor, ...]


@dataclass(frozen=True)
class ModelIssue:
    field: str | None
    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _immutable_mapping(self.details))


@dataclass(frozen=True)
class ModelResult:
    model_uid: UUID
    values: Mapping[str, Any]
    compatible: bool
    missing_fields: tuple[str, ...] = ()
    additional_fields: tuple[str, ...] = ()
    issues: tuple[ModelIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", _immutable_mapping(self.values))


class DatamodelComponent:
    """Model registry and field orchestration over an ElementComponent."""

    component_id = "datamodel"

    def __init__(
        self,
        element: ElementComponent | None = None,
        elements: tuple[ElementBinding, ...] = (),
    ) -> None:
        self.element = element or ElementComponent.with_core_types()
        self._default_scope = (
            self.element.create_extension_scope(elements)
            if elements
            else None
        )
        self._models: dict[UUID, RegisteredModel] = {}

    @property
    def registration_count(self) -> int:
        return len(self._models)

    @property
    def default_element_scope(self) -> ElementScope:
        """Return the current element fallback used by new model registrations."""
        return self._default_scope or self.element.default_scope

    def register_model(
        self,
        definition: ModelDefinition,
        *,
        elements: tuple[ElementBinding, ...] = (),
        fallback_elements: ElementScope | None = None,
    ) -> RegisteredModel:
        parent = fallback_elements or self.default_element_scope
        scope = self.element.create_scope(elements, parent=parent)
        processors = {
            field_name: self.element.bind(spec, scope)
            for field_name, spec in definition.schema.items()
        }
        model = RegisteredModel(
            uid=uuid4(),
            definition=definition,
            element_scope=scope,
            processors=processors,
        )
        self._models[model.uid] = model
        return model

    def get_model(self, uid: UUID) -> RegisteredModel:
        try:
            return self._models[uid]
        except KeyError as exc:
            raise ModelNotFound(f"model registration not found: {uid}") from exc

    def list_models(
        self,
        *,
        name: str | None = None,
        version: str | None = None,
    ) -> tuple[RegisteredModelDescriptor, ...]:
        return tuple(
            self._descriptor(model)
            for model in self._models.values()
            if (name is None or model.definition.name == name)
            and (version is None or model.definition.version == version)
        )

    def instantiate(
        self,
        model: RegisteredModel | UUID,
        raw: Mapping[str, Any],
    ) -> ModelResult:
        registered = self.get_model(model) if isinstance(model, UUID) else model
        if self._models.get(registered.uid) is not registered:
            raise ModelNotFound(f"model registration not found: {registered.uid}")
        if not isinstance(raw, Mapping):
            raise DatamodelError("model input must be a mapping")

        schema_fields = set(registered.definition.schema)
        raw_fields = set(raw)
        missing = tuple(sorted(schema_fields - raw_fields))
        additional = tuple(sorted(raw_fields - schema_fields))
        values: dict[str, Any] = {}
        issues: list[ModelIssue] = [
            ModelIssue(
                field=field_name,
                code="missing_field",
                message=f"required field is missing: {field_name}",
            )
            for field_name in missing
        ]
        issues.extend(
            ModelIssue(
                field=field_name,
                code="additional_field",
                message=f"field is not defined by the model: {field_name}",
            )
            for field_name in additional
        )

        compatible = not missing and not additional
        for field_name in registered.definition.schema:
            if field_name not in raw:
                continue
            result = registered.processors[field_name].decode(raw[field_name])
            if result.compatible:
                values[field_name] = result.value
            else:
                compatible = False
            issues.extend(
                ModelIssue(
                    field=field_name,
                    code=issue.code,
                    message=issue.message,
                    details=issue.details,
                )
                for issue in result.issues
            )

        return ModelResult(
            model_uid=registered.uid,
            values=values,
            compatible=compatible,
            missing_fields=missing,
            additional_fields=additional,
            issues=tuple(issues),
        )

    def _descriptor(self, model: RegisteredModel) -> RegisteredModelDescriptor:
        return RegisteredModelDescriptor(
            uid=model.uid,
            definition_uid=model.definition.uid,
            name=model.definition.name,
            version=model.definition.version,
            elements=self.element.describe_scope(model.element_scope),
        )
