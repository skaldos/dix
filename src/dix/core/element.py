from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping, Protocol

ElementBindingMode = Literal["define", "wrap", "replace"]
ElementTypeSource = Literal["core", "extension", "model"]


class ElementError(Exception):
    """Base error for element configuration and resolution."""


class ElementBindingError(ElementError):
    """Raised when an element binding chain is invalid."""


class UnknownElementType(ElementError):
    """Raised when an element type cannot be resolved."""


def _immutable_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class ElementSpec:
    type: str
    config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        type_name = self.type.strip()
        if not type_name:
            raise ElementBindingError("element type must not be empty")
        object.__setattr__(self, "type", type_name)
        object.__setattr__(self, "config", _immutable_mapping(self.config))


@dataclass(frozen=True)
class ElementIssue:
    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _immutable_mapping(self.details))


@dataclass(frozen=True)
class ElementResult:
    value: Any
    compatible: bool
    issues: tuple[ElementIssue, ...] = ()


class ElementProcessor(Protocol):
    def decode(self, raw: Any) -> ElementResult:
        """Decode one native Python value."""


class ElementHandler(Protocol):
    handler_id: str

    def bind(
        self,
        spec: ElementSpec,
        delegate: ElementProcessor | None,
    ) -> ElementProcessor:
        """Validate configuration and create an immutable processor."""


@dataclass(frozen=True)
class ElementBinding:
    type_name: str
    handler_id: str
    handler: ElementHandler
    mode: ElementBindingMode

    def __post_init__(self) -> None:
        type_name = self.type_name.strip()
        handler_id = self.handler_id.strip()
        if not type_name:
            raise ElementBindingError("binding type_name must not be empty")
        if not handler_id:
            raise ElementBindingError("binding handler_id must not be empty")
        if handler_id != self.handler.handler_id:
            raise ElementBindingError(
                f"binding handler_id '{handler_id}' does not match handler "
                f"'{self.handler.handler_id}'"
            )
        object.__setattr__(self, "type_name", type_name)
        object.__setattr__(self, "handler_id", handler_id)


@dataclass(frozen=True)
class ElementScope:
    bindings: Mapping[str, ElementBinding]
    source: ElementTypeSource
    parent: ElementScope | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "bindings", MappingProxyType(dict(self.bindings)))


@dataclass(frozen=True)
class ElementTypeDescriptor:
    type_name: str
    handler_id: str
    source: ElementTypeSource
    mode: ElementBindingMode


@dataclass(frozen=True)
class _AnyProcessor:
    def decode(self, raw: Any) -> ElementResult:
        return ElementResult(value=raw, compatible=True)


@dataclass(frozen=True)
class _AnyHandler:
    handler_id: str = "core.any"

    def bind(
        self, spec: ElementSpec, delegate: ElementProcessor | None
    ) -> ElementProcessor:
        _require_base_binding(spec, delegate)
        return _AnyProcessor()


@dataclass(frozen=True)
class _StrictTypeProcessor:
    expected_type: type[Any]
    expected_name: str
    reject_bool: bool = False

    def decode(self, raw: Any) -> ElementResult:
        compatible = isinstance(raw, self.expected_type) and not (
            self.reject_bool and isinstance(raw, bool)
        )
        if compatible:
            return ElementResult(value=raw, compatible=True)
        return ElementResult(
            value=None,
            compatible=False,
            issues=(
                ElementIssue(
                    code="incompatible_type",
                    message=f"expected {self.expected_name}, got {type(raw).__name__}",
                    details={
                        "expected": self.expected_name,
                        "received": type(raw).__name__,
                    },
                ),
            ),
        )


@dataclass(frozen=True)
class _StrictTypeHandler:
    handler_id: str
    expected_type: type[Any]
    expected_name: str
    reject_bool: bool = False

    def bind(
        self, spec: ElementSpec, delegate: ElementProcessor | None
    ) -> ElementProcessor:
        _require_base_binding(spec, delegate)
        return _StrictTypeProcessor(
            expected_type=self.expected_type,
            expected_name=self.expected_name,
            reject_bool=self.reject_bool,
        )


def _require_base_binding(spec: ElementSpec, delegate: ElementProcessor | None) -> None:
    if delegate is not None:
        raise ElementBindingError(f"core handler for '{spec.type}' cannot wrap a delegate")
    if spec.config:
        raise ElementBindingError(f"core element '{spec.type}' does not accept configuration")


def _binding(
    type_name: str,
    handler: ElementHandler,
    *,
    mode: ElementBindingMode = "define",
) -> ElementBinding:
    return ElementBinding(
        type_name=type_name,
        handler_id=handler.handler_id,
        handler=handler,
        mode=mode,
    )


class ElementComponent:
    """Registry and binding engine for atomic technical value handlers."""

    component_id = "element"

    def __init__(self, core_bindings: tuple[ElementBinding, ...]) -> None:
        self._core_scope = self._make_scope(core_bindings, source="core", parent=None)
        self._extension_bindings: dict[str, ElementBinding] = {}

    @classmethod
    def with_core_types(cls) -> ElementComponent:
        return cls(
            (
                _binding("any", _AnyHandler()),
                _binding(
                    "string",
                    _StrictTypeHandler(
                        handler_id="core.string",
                        expected_type=str,
                        expected_name="string",
                    ),
                ),
                _binding(
                    "integer",
                    _StrictTypeHandler(
                        handler_id="core.integer",
                        expected_type=int,
                        expected_name="integer",
                        reject_bool=True,
                    ),
                ),
                _binding(
                    "boolean",
                    _StrictTypeHandler(
                        handler_id="core.boolean",
                        expected_type=bool,
                        expected_name="boolean",
                    ),
                ),
            )
        )

    @property
    def default_scope(self) -> ElementScope:
        if not self._extension_bindings:
            return self._core_scope
        return ElementScope(
            bindings=self._extension_bindings,
            source="extension",
            parent=self._core_scope,
        )

    def register_extension(self, binding: ElementBinding) -> None:
        if binding.mode != "define":
            raise ElementBindingError("component extensions must use mode='define'")
        if self._has_type(self.default_scope, binding.type_name):
            raise ElementBindingError(
                f"element type already exists and cannot be extended globally: {binding.type_name}"
            )
        self._extension_bindings[binding.type_name] = binding

    def list_types(self) -> tuple[ElementTypeDescriptor, ...]:
        descriptors: dict[str, ElementTypeDescriptor] = {}
        self._collect_descriptors(self.default_scope, descriptors)
        return tuple(descriptors[name] for name in sorted(descriptors))

    def describe_type(self, type_name: str) -> ElementTypeDescriptor:
        descriptors = {item.type_name: item for item in self.list_types()}
        try:
            return descriptors[type_name]
        except KeyError as exc:
            raise UnknownElementType(f"unknown element type: {type_name}") from exc

    def create_scope(
        self,
        bindings: tuple[ElementBinding, ...],
        parent: ElementScope | None = None,
    ) -> ElementScope:
        return self._make_scope(
            bindings,
            source="model",
            parent=parent or self.default_scope,
        )

    def create_extension_scope(
        self,
        bindings: tuple[ElementBinding, ...],
        parent: ElementScope | None = None,
    ) -> ElementScope:
        if any(binding.mode != "define" for binding in bindings):
            raise ElementBindingError("component extensions must use mode='define'")
        return self._make_scope(
            bindings,
            source="extension",
            parent=parent or self.default_scope,
        )

    def describe_scope(self, scope: ElementScope) -> tuple[ElementTypeDescriptor, ...]:
        descriptors: list[ElementTypeDescriptor] = []
        current: ElementScope | None = scope
        while current is not None:
            descriptors.extend(
                ElementTypeDescriptor(
                    type_name=type_name,
                    handler_id=binding.handler_id,
                    source=current.source,
                    mode=binding.mode,
                )
                for type_name, binding in sorted(current.bindings.items())
            )
            current = current.parent
        return tuple(descriptors)

    def bind(self, spec: ElementSpec, scope: ElementScope | None = None) -> ElementProcessor:
        final_scope = scope or self.default_scope
        processor = self._bind_from_scope(spec, final_scope)
        if processor is None:
            raise UnknownElementType(f"unknown element type: {spec.type}")
        return processor

    def _make_scope(
        self,
        bindings: tuple[ElementBinding, ...],
        *,
        source: ElementTypeSource,
        parent: ElementScope | None,
    ) -> ElementScope:
        by_name: dict[str, ElementBinding] = {}
        for binding in bindings:
            if binding.type_name in by_name:
                raise ElementBindingError(
                    f"duplicate element binding in one scope: {binding.type_name}"
                )
            fallback_exists = self._has_type(parent, binding.type_name)
            if binding.mode == "define" and fallback_exists:
                raise ElementBindingError(
                    f"cannot define existing element type: {binding.type_name}"
                )
            if binding.mode in {"wrap", "replace"} and not fallback_exists:
                raise ElementBindingError(
                    f"cannot {binding.mode} missing element type: {binding.type_name}"
                )
            by_name[binding.type_name] = binding
        return ElementScope(bindings=by_name, source=source, parent=parent)

    def _bind_from_scope(
        self, spec: ElementSpec, scope: ElementScope | None
    ) -> ElementProcessor | None:
        if scope is None:
            return None
        binding = scope.bindings.get(spec.type)
        if binding is None:
            return self._bind_from_scope(spec, scope.parent)
        if binding.mode == "wrap":
            delegate = self._bind_from_scope(spec, scope.parent)
            if delegate is None:
                raise ElementBindingError(f"missing delegate for wrapped type: {spec.type}")
            return binding.handler.bind(spec, delegate)
        if binding.mode == "replace":
            return binding.handler.bind(spec, None)
        return binding.handler.bind(spec, None)

    def _has_type(self, scope: ElementScope | None, type_name: str) -> bool:
        current = scope
        while current is not None:
            if type_name in current.bindings:
                return True
            current = current.parent
        return False

    def _collect_descriptors(
        self,
        scope: ElementScope | None,
        descriptors: dict[str, ElementTypeDescriptor],
    ) -> None:
        if scope is None:
            return
        self._collect_descriptors(scope.parent, descriptors)
        for type_name, binding in scope.bindings.items():
            descriptors[type_name] = ElementTypeDescriptor(
                type_name=type_name,
                handler_id=binding.handler_id,
                source=scope.source,
                mode=binding.mode,
            )
