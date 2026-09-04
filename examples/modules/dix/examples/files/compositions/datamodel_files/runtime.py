from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from dix.core import (
    DatamodelComponent,
    ElementBinding,
    ElementProcessor,
    ElementResult,
    ElementSpec,
    ModelDefinition,
    ModelIssue,
    ModelResult,
    RegisteredModel,
)
from dix.core.composition import CompositionRuntimeContext


class DatamodelFilesError(Exception):
    """Raised when model or data files cannot be consumed deterministically."""


class _ModelHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("version")
    @classmethod
    def normalize_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class _FieldDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)

    @field_validator("type")
    @classmethod
    def normalize_type(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class _ModelFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: _ModelHeader
    fields: dict[str, _FieldDefinition]


class _DataModelReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str | None = None


class _DataEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: _DataModelReference
    data: dict[str, Any]


class _RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_path: str = Field(min_length=1)
    data_path: str = Field(min_length=1)


@dataclass(frozen=True)
class _IntegerStringProcessor:
    delegate: ElementProcessor

    def decode(self, raw: Any) -> ElementResult:
        value = int(raw) if isinstance(raw, str) and raw.isdecimal() else raw
        return self.delegate.decode(value)


@dataclass(frozen=True)
class _IntegerStringHandler:
    handler_id: str = "datamodel_files.integer_string"

    def bind(
        self,
        spec: ElementSpec,
        delegate: ElementProcessor | None,
    ) -> ElementProcessor:
        if delegate is None:
            raise DatamodelFilesError("integer string handler requires a delegate")
        return _IntegerStringProcessor(delegate)


def _integer_string_binding() -> ElementBinding:
    handler = _IntegerStringHandler()
    return ElementBinding(
        type_name="integer",
        handler_id=handler.handler_id,
        handler=handler,
        mode="wrap",
    )


class Runtime:
    """Trusted TOML/JSON adapter around one local datamodel capability."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
        datamodel: DatamodelComponent,
    ) -> None:
        self.context = context
        self.config = config
        self.datamodel = datamodel
        self._models: dict[tuple[str, str | None], list[RegisteredModel]] = {}
        self._configured_model: RegisteredModel | None = None

    def register_model(self, path: Path) -> RegisteredModel:
        """Register one TOML model source in this composition instance."""
        raw = self._read_toml(path)
        try:
            parsed = _ModelFile.model_validate(raw)
            definition = ModelDefinition(
                uid=uuid4(),
                name=parsed.model.name,
                version=parsed.model.version,
                schema={
                    field_name: ElementSpec(type=field.type)
                    for field_name, field in parsed.fields.items()
                },
            )
            registered = self.datamodel.register_model(
                definition,
                elements=(_integer_string_binding(),),
            )
        except (ValidationError, ValueError) as exc:
            raise DatamodelFilesError(f"invalid model file {path}: {exc}") from exc
        key = (definition.name, definition.version)
        self._models.setdefault(key, []).append(registered)
        return registered

    def load_data(self, json_string: str) -> ModelResult:
        """Load one JSON data envelope against a registered model."""
        try:
            raw = json.loads(json_string)
            envelope = _DataEnvelope.model_validate(raw)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise DatamodelFilesError(f"invalid data input: {exc}") from exc
        key = (envelope.model.name, envelope.model.version)
        models = self._models.get(key, [])
        if not models:
            name, version = key
            raise DatamodelFilesError(
                f"model is not registered in this composition: name={name!r}, version={version!r}"
            )
        if len(models) > 1:
            name, version = key
            raise DatamodelFilesError(
                f"model reference is ambiguous in this composition: "
                f"name={name!r}, version={version!r}"
            )
        return self.datamodel.instantiate(models[0], envelope.data)

    def run(self) -> dict[str, Any]:
        """Run the configured side-effect-free file demo."""
        try:
            parsed = _RuntimeConfig.model_validate(self.config)
        except ValidationError as exc:
            raise DatamodelFilesError(f"invalid datamodel_files config: {exc}") from exc
        model_path = self._resolve_path(parsed.model_path)
        data_path = self._resolve_path(parsed.data_path)
        if self._configured_model is None:
            self._configured_model = self.register_model(model_path)
        try:
            json_string = data_path.read_text()
        except OSError as exc:
            raise DatamodelFilesError(f"cannot load data file {data_path}: {exc}") from exc
        return _model_result_payload(self.load_data(json_string))

    def _resolve_path(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser()
        return (
            path.resolve()
            if path.is_absolute()
            else (self.context.config_base_dir / path).resolve()
        )

    @staticmethod
    def _read_toml(path: Path) -> Mapping[str, Any]:
        try:
            return tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise DatamodelFilesError(f"cannot load model file {path}: {exc}") from exc


def _model_result_payload(result: ModelResult) -> dict[str, Any]:
    return {
        "model_uid": str(result.model_uid),
        "values": dict(result.values),
        "compatible": result.compatible,
        "missing_fields": list(result.missing_fields),
        "additional_fields": list(result.additional_fields),
        "issues": [_issue_payload(issue) for issue in result.issues],
    }


def _issue_payload(issue: ModelIssue) -> dict[str, Any]:
    return {
        "field": issue.field,
        "code": issue.code,
        "message": issue.message,
        "details": dict(issue.details),
    }
