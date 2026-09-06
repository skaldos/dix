from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from .datamodel import ModelDefinition
from .element import ElementSpec

FunctionProjection = Literal["exact", "fallback_any"]


@dataclass(frozen=True)
class FunctionParameterDescriptor:
    name: str
    kind: inspect._ParameterKind
    required: bool
    has_default: bool
    default: object
    annotation: object
    element_type: str
    projection: FunctionProjection


@dataclass(frozen=True)
class FunctionValueContract:
    element: ElementSpec
    annotation: object
    projection: FunctionProjection


@dataclass(frozen=True)
class FunctionContract:
    input_model: ModelDefinition
    parameters: tuple[FunctionParameterDescriptor, ...]
    output: FunctionValueContract


def derive_function_contract(
    owner_id: str,
    function_id: str,
    signature: inspect.Signature,
) -> FunctionContract:
    parameters: list[FunctionParameterDescriptor] = []
    schema: dict[str, ElementSpec] = {}
    for parameter in signature.parameters.values():
        element_type, projection = _project_annotation(parameter.annotation)
        if parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            element_type, projection = "any", "fallback_any"
        has_default = parameter.default is not inspect.Parameter.empty
        required = not has_default and parameter.kind not in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }
        parameters.append(
            FunctionParameterDescriptor(
                name=parameter.name,
                kind=parameter.kind,
                required=required,
                has_default=has_default,
                default=parameter.default,
                annotation=parameter.annotation,
                element_type=element_type,
                projection=projection,
            )
        )
        schema[parameter.name] = ElementSpec(element_type)

    output_type, output_projection = _project_annotation(signature.return_annotation)
    return FunctionContract(
        input_model=ModelDefinition(
            uid=uuid4(),
            name=f"{owner_id}/{function_id}/input",
            version=None,
            schema=schema,
        ),
        parameters=tuple(parameters),
        output=FunctionValueContract(
            element=ElementSpec(output_type),
            annotation=signature.return_annotation,
            projection=output_projection,
        ),
    )


def _project_annotation(annotation: object) -> tuple[str, FunctionProjection]:
    annotation_name = annotation if isinstance(annotation, str) else None
    if annotation is None or annotation is type(None) or annotation_name in ("None", "NoneType"):
        return "null", "exact"
    if annotation is str or annotation_name == "str":
        return "string", "exact"
    if annotation is int or annotation_name == "int":
        return "integer", "exact"
    if annotation is float or annotation_name == "float":
        return "number", "exact"
    if annotation is bool or annotation_name == "bool":
        return "boolean", "exact"
    if annotation is bytes or annotation_name == "bytes":
        return "binary", "exact"
    if annotation is list or annotation_name == "list":
        return "array", "exact"
    if annotation is dict or annotation_name == "dict":
        return "object", "exact"
    if (
        annotation is Any
        or annotation is object
        or annotation is inspect.Signature.empty
        or annotation_name in ("Any", "typing.Any", "object")
    ):
        return "any", "fallback_any"
    return "any", "fallback_any"
