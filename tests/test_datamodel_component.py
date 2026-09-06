from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass
from typing import Any
from uuid import uuid4

import pytest

from dix.core import (
    DatamodelComponent,
    DatamodelError,
    ElementBinding,
    ElementBindingError,
    ElementHandler,
    ElementProcessor,
    ElementResult,
    ElementSpec,
    ModelDefinition,
    ModelNotFound,
)


@dataclass(frozen=True)
class NumericStringProcessor:
    delegate: ElementProcessor

    def decode(self, raw: Any) -> ElementResult:
        value = int(raw) if isinstance(raw, str) and raw.isdecimal() else raw
        return self.delegate.decode(value)


@dataclass(frozen=True)
class NumericStringHandler:
    handler_id: str = "test.numeric_string"

    def bind(
        self, spec: ElementSpec, delegate: ElementProcessor | None
    ) -> ElementProcessor:
        if delegate is None:
            raise AssertionError("numeric string handler requires a delegate")
        return NumericStringProcessor(delegate)


@dataclass(frozen=True)
class ConstantProcessor:
    value: Any

    def decode(self, raw: Any) -> ElementResult:
        return ElementResult(value=self.value, compatible=True)


@dataclass(frozen=True)
class ConstantHandler:
    handler_id: str = "test.constant"

    def bind(
        self, spec: ElementSpec, delegate: ElementProcessor | None
    ) -> ElementProcessor:
        return ConstantProcessor(spec.config.get("value"))


def binding(
    type_name: str,
    handler: ElementHandler,
    mode: str,
) -> ElementBinding:
    return ElementBinding(
        type_name=type_name,
        handler_id=handler.handler_id,
        handler=handler,
        mode=mode,  # type: ignore[arg-type]
    )


def definition() -> ModelDefinition:
    return ModelDefinition(
        uid=uuid4(),
        name="user_request",
        version="1",
        schema={
            "username": ElementSpec(type="string"),
            "age": ElementSpec(type="integer"),
            "active": ElementSpec(type="boolean"),
            "metadata": ElementSpec(type="any"),
        },
    )


def test_exact_mapping_instantiates_through_core_elements() -> None:
    datamodel = DatamodelComponent()
    model = datamodel.register_model(definition())

    result = datamodel.instantiate(
        model,
        {
            "username": "alice",
            "age": 42,
            "active": True,
            "metadata": {"source": "manual"},
        },
    )

    assert result.compatible is True
    assert dict(result.values) == {
        "username": "alice",
        "age": 42,
        "active": True,
        "metadata": {"source": "manual"},
    }
    assert result.missing_fields == ()
    assert result.additional_fields == ()
    assert result.issues == ()


def test_extended_native_core_elements_instantiate_together() -> None:
    datamodel = DatamodelComponent()
    model = datamodel.register_model(
        ModelDefinition(
            uid=uuid4(),
            name="native_values",
            schema={
                "nothing": ElementSpec(type="null"),
                "number": ElementSpec(type="number"),
                "payload": ElementSpec(type="binary"),
                "items": ElementSpec(type="array"),
                "attributes": ElementSpec(type="object"),
            },
        )
    )
    items = ["one", 2]
    attributes = {"source": "test"}
    payload = b"dix"

    result = datamodel.instantiate(
        model,
        {
            "nothing": None,
            "number": 1.5,
            "payload": payload,
            "items": items,
            "attributes": attributes,
        },
    )

    assert result.compatible is True
    assert result.values["nothing"] is None
    assert result.values["number"] == 1.5
    assert result.values["payload"] is payload
    assert result.values["items"] is items
    assert result.values["attributes"] is attributes

    incompatible = datamodel.instantiate(
        model,
        {
            "nothing": "",
            "number": True,
            "payload": bytearray(payload),
            "items": tuple(items),
            "attributes": list(attributes.items()),
        },
    )

    assert incompatible.compatible is False
    assert [issue.code for issue in incompatible.issues] == ["incompatible_type"] * 5


def test_model_result_separates_missing_additional_and_element_issues() -> None:
    datamodel = DatamodelComponent()
    model = datamodel.register_model(definition())

    result = datamodel.instantiate(
        model,
        {"age": "not-an-int", "active": "true", "metadata": None, "extra": True},
    )

    assert result.compatible is False
    assert result.missing_fields == ("username",)
    assert result.additional_fields == ("extra",)
    assert [(issue.field, issue.code) for issue in result.issues] == [
        ("username", "missing_field"),
        ("extra", "additional_field"),
        ("age", "incompatible_type"),
        ("active", "incompatible_type"),
    ]
    assert dict(result.values) == {"metadata": None}


def test_same_definition_can_be_registered_more_than_once() -> None:
    datamodel = DatamodelComponent()
    shared_definition = definition()

    first = datamodel.register_model(shared_definition)
    second = datamodel.register_model(shared_definition)

    assert first.uid != second.uid
    assert first.definition is second.definition
    assert datamodel.get_model(first.uid) is first
    assert [item.uid for item in datamodel.list_models(name="user_request", version="1")] == [
        first.uid,
        second.uid,
    ]


def test_model_local_wrapper_does_not_change_another_registration() -> None:
    datamodel = DatamodelComponent()
    shared_definition = definition()
    base = datamodel.register_model(shared_definition)
    wrapped = datamodel.register_model(
        shared_definition,
        elements=(binding("integer", NumericStringHandler(), "wrap"),),
    )

    wrapped_result = datamodel.instantiate(
        wrapped,
        {"username": "alice", "age": "42", "active": False, "metadata": {}},
    )
    base_result = datamodel.instantiate(
        base,
        {"username": "alice", "age": "42", "active": False, "metadata": {}},
    )

    assert wrapped_result.compatible is True
    assert wrapped_result.values["age"] == 42
    assert base_result.compatible is False


def test_datamodel_extensions_can_only_define_new_types() -> None:
    constant = ConstantHandler()
    custom = DatamodelComponent(
        elements=(binding("constant", constant, "define"),)
    )
    model = custom.register_model(
        ModelDefinition(
            uid=uuid4(),
            name="constant_model",
            schema={
                "value": ElementSpec(type="constant", config={"value": "fixed"}),
            },
        )
    )

    assert custom.instantiate(model, {"value": "ignored"}).values["value"] == "fixed"

    with pytest.raises(ElementBindingError, match="cannot define existing"):
        DatamodelComponent(elements=(binding("string", constant, "define"),))
    with pytest.raises(ElementBindingError, match="mode='define'"):
        DatamodelComponent(elements=(binding("string", constant, "wrap"),))


def test_registered_model_can_explicitly_inherit_an_existing_scope() -> None:
    datamodel = DatamodelComponent()
    shared_definition = definition()
    first = datamodel.register_model(
        shared_definition,
        elements=(binding("integer", NumericStringHandler(), "wrap"),),
    )
    second = datamodel.register_model(
        shared_definition,
        fallback_elements=first.element_scope,
    )

    assert datamodel.instantiate(
        second,
        {"username": "alice", "age": "42", "active": True, "metadata": {}},
    ).compatible
    assert datamodel.instantiate(
        first,
        {"username": "alice", "age": "42", "active": True, "metadata": {}},
    ).compatible


def test_definitions_and_registrations_are_immutable_and_unknown_models_fail() -> None:
    datamodel = DatamodelComponent()
    model_definition = definition()
    model = datamodel.register_model(model_definition)

    with pytest.raises(TypeError):
        model_definition.schema["other"] = ElementSpec(type="any")  # type: ignore[index]
    with pytest.raises(TypeError):
        model.processors["other"] = model.processors["age"]  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        model.uid = uuid4()  # type: ignore[misc]
    with pytest.raises(ModelNotFound):
        datamodel.get_model(uuid4())
    with pytest.raises(DatamodelError, match="must be a mapping"):
        datamodel.instantiate(model, ["not", "a", "mapping"])  # type: ignore[arg-type]
