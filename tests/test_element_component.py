from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from dix.core import (
    ElementBinding,
    ElementBindingError,
    ElementComponent,
    ElementIssue,
    ElementProcessor,
    ElementResult,
    ElementSpec,
    UnknownElementType,
)


@dataclass(frozen=True)
class PrefixProcessor:
    prefix: str

    def decode(self, raw: Any) -> ElementResult:
        if not isinstance(raw, str):
            return ElementResult(
                value=None,
                compatible=False,
                issues=(ElementIssue(code="not_string", message="expected a string"),),
            )
        return ElementResult(value=f"{self.prefix}{raw}", compatible=True)


@dataclass(frozen=True)
class PrefixHandler:
    handler_id: str = "test.prefix"

    def bind(
        self, spec: ElementSpec, delegate: ElementProcessor | None
    ) -> ElementProcessor:
        assert delegate is None
        return PrefixProcessor(prefix=str(spec.config.get("prefix", "")))


@dataclass(frozen=True)
class IntegerStringProcessor:
    delegate: ElementProcessor

    def decode(self, raw: Any) -> ElementResult:
        value = int(raw) if isinstance(raw, str) and raw.isdecimal() else raw
        return self.delegate.decode(value)


@dataclass(frozen=True)
class IntegerStringHandler:
    handler_id: str = "test.integer_string"

    def bind(
        self, spec: ElementSpec, delegate: ElementProcessor | None
    ) -> ElementProcessor:
        assert delegate is not None
        return IntegerStringProcessor(delegate=delegate)


def binding(type_name: str, handler, mode: str) -> ElementBinding:
    return ElementBinding(
        type_name=type_name,
        handler_id=handler.handler_id,
        handler=handler,
        mode=mode,
    )


def test_core_element_types_are_strict_and_inspectable() -> None:
    component = ElementComponent.with_core_types()

    assert component.bind(ElementSpec(type="any")).decode(None).compatible is True
    assert component.bind(ElementSpec(type="any")).decode({"a": [1]}).value == {"a": [1]}
    assert component.bind(ElementSpec(type="string")).decode("value").compatible is True
    assert component.bind(ElementSpec(type="string")).decode(1).compatible is False
    assert component.bind(ElementSpec(type="integer")).decode(42).value == 42
    assert component.bind(ElementSpec(type="integer")).decode(True).compatible is False
    assert component.bind(ElementSpec(type="integer")).decode("42").compatible is False
    assert component.bind(ElementSpec(type="boolean")).decode(True).value is True
    assert component.bind(ElementSpec(type="boolean")).decode(False).value is False
    for incompatible in (0, 1, "true", "false", None, []):
        result = component.bind(ElementSpec(type="boolean")).decode(incompatible)
        assert result.compatible is False
        assert result.issues[0].code == "incompatible_type"
    assert {item.type_name for item in component.list_types()} == {
        "any",
        "boolean",
        "integer",
        "string",
    }
    assert component.describe_type("integer").handler_id == "core.integer"
    assert component.describe_type("boolean").handler_id == "core.boolean"

    with pytest.raises(ElementBindingError, match="does not accept configuration"):
        component.bind(ElementSpec(type="boolean", config={"parse": True}))


def test_extension_can_define_a_new_type_but_not_override_core() -> None:
    component = ElementComponent.with_core_types()
    component.register_extension(binding("prefixed", PrefixHandler(), "define"))

    result = component.bind(
        ElementSpec(type="prefixed", config={"prefix": "id-"})
    ).decode("123")
    assert result.value == "id-123"
    assert component.describe_type("prefixed").source == "extension"

    with pytest.raises(ElementBindingError, match="already exists"):
        component.register_extension(binding("string", PrefixHandler(), "define"))


def test_model_wrapper_receives_effective_delegate_without_changing_default() -> None:
    component = ElementComponent.with_core_types()
    scope = component.create_scope(
        (binding("integer", IntegerStringHandler(), "wrap"),)
    )

    wrapped = component.bind(ElementSpec(type="integer"), scope).decode("42")
    default = component.bind(ElementSpec(type="integer")).decode("42")

    assert wrapped.compatible is True
    assert wrapped.value == 42
    assert default.compatible is False


def test_model_replacement_is_local_and_does_not_receive_a_delegate() -> None:
    component = ElementComponent.with_core_types()
    scope = component.create_scope((binding("string", PrefixHandler(), "replace"),))

    replaced = component.bind(
        ElementSpec(type="string", config={"prefix": "local-"}), scope
    ).decode("value")
    default = component.bind(ElementSpec(type="string")).decode("value")

    assert replaced.value == "local-value"
    assert default.value == "value"


def test_invalid_bindings_and_unknown_types_fail_deterministically() -> None:
    component = ElementComponent.with_core_types()
    handler = PrefixHandler()

    with pytest.raises(ElementBindingError, match="cannot define existing"):
        component.create_scope((binding("string", handler, "define"),))
    with pytest.raises(ElementBindingError, match="cannot wrap missing"):
        component.create_scope((binding("missing", handler, "wrap"),))
    with pytest.raises(ElementBindingError, match="cannot replace missing"):
        component.create_scope((binding("missing", handler, "replace"),))
    with pytest.raises(ElementBindingError, match="duplicate"):
        component.create_scope(
            (
                binding("one", handler, "define"),
                binding("one", handler, "define"),
            )
        )
    with pytest.raises(UnknownElementType, match="unknown element type"):
        component.bind(ElementSpec(type="missing"))


def test_scope_bindings_are_immutable() -> None:
    component = ElementComponent.with_core_types()
    scope = component.create_scope((binding("new", PrefixHandler(), "define"),))

    with pytest.raises(TypeError):
        scope.bindings["other"] = binding("other", PrefixHandler(), "define")  # type: ignore[index]
