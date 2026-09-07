from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from dix.core import NornComponent, StrandDefinition, StrandDescriptor, model_element
from dix.core.application import (
    ApplicationComponent,
    ApplicationFunctionDescriptor,
    ApplicationInstanceSpec,
)
from dix.core.composition import CompositionRuntimeContext


class ApplicationKnotError(Exception):
    """Raised when an application function cannot be bound as a local strand."""


@dataclass(frozen=True)
class _ApplicationTarget:
    strand_id: str
    application_id: str
    function: ApplicationFunctionDescriptor
    config: Mapping[str, object]


class Runtime:
    """Knot that binds loaded application functions to local Norn strands."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
        application: ApplicationComponent,
        norn: NornComponent,
    ) -> None:
        self.context = context
        self.config = config
        self.application = application
        self.norn = norn
        self._targets: dict[str, _ApplicationTarget] = {}

    def bind_application(
        self,
        application_id: str,
        application_config: Mapping[str, object] | None = None,
    ) -> tuple[StrandDescriptor, ...]:
        descriptor = self.application.describe_application(application_id)
        return tuple(
            self.bind_function(
                f"{application_id}/{function.id}",
                application_id,
                function.id,
                application_config,
            )
            for function in descriptor.functions
        )

    def bind_function(
        self,
        strand_id: str,
        application_id: str,
        function_id: str,
        application_config: Mapping[str, object] | None = None,
    ) -> StrandDescriptor:
        function = self.application.describe_function(application_id, function_id)
        target = _ApplicationTarget(
            strand_id=strand_id,
            application_id=application_id,
            function=function,
            config=MappingProxyType(
                {} if application_config is None else dict(application_config)
            ),
        )
        existing = self._targets.get(strand_id)
        if existing is not None:
            if _same_target(existing, target):
                return self.norn.describe(strand_id)
            raise ApplicationKnotError(
                f"strand is already bound to a different application target: {strand_id}"
            )

        self.norn.register(
            StrandDefinition(
                id=strand_id,
                input_element=model_element(function.contract.input_model),
                output_element=function.contract.output.element,
            )
        )
        self.norn.bind(
            strand_id,
            handler_id=f"application:{application_id}/{function_id}",
            handler=lambda value: self._execute(target, value),
        )
        self._targets[strand_id] = target
        return self.norn.describe(strand_id)

    def describe_strand(self, strand_id: str) -> StrandDescriptor:
        return self.norn.describe(strand_id)

    def strands(self) -> tuple[StrandDescriptor, ...]:
        return self.norn.strands()

    async def call(self, strand_id: str, value: object) -> object:
        return await self.norn.call(strand_id, value)

    async def _execute(self, target: _ApplicationTarget, value: object) -> object:
        if not isinstance(value, Mapping):
            raise ApplicationKnotError("application strand input must be a model mapping")
        args, kwargs = _call_arguments(target.function, value)
        execution_id = uuid4().hex
        owner_scope_id = f"application-knot:{self.context.instance_id}:{execution_id}"
        instance_id = f"call-{execution_id}"
        created = False
        try:
            instance = self.application.create_instance(
                ApplicationInstanceSpec(
                    id=instance_id,
                    use=target.application_id,
                    config=target.config,
                    config_base_dir=self.context.config_base_dir,
                ),
                owner_scope_id=owner_scope_id,
            )
            created = True
            result = instance.api.require(target.function.id)(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result
        finally:
            if created:
                self.application.destroy_instance(owner_scope_id, instance_id)


def _same_target(first: _ApplicationTarget, second: _ApplicationTarget) -> bool:
    return (
        first.application_id == second.application_id
        and first.function.id == second.function.id
        and dict(first.config) == dict(second.config)
    )


def _call_arguments(
    descriptor: ApplicationFunctionDescriptor,
    values: Mapping[str, object],
) -> tuple[tuple[object, ...], dict[str, object]]:
    positional: list[object] = []
    keyword: dict[str, object] = {}
    for parameter in descriptor.contract.parameters:
        value = values[parameter.name]
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            positional.append(value)
        elif parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
                raise ApplicationKnotError(
                    f"variadic positional input must be a sequence: {parameter.name}"
                )
            positional.extend(value)
        elif parameter.kind is inspect.Parameter.VAR_KEYWORD:
            if not isinstance(value, Mapping) or not all(
                isinstance(key, str) for key in value
            ):
                raise ApplicationKnotError(
                    f"variadic keyword input must be a string-keyed mapping: {parameter.name}"
                )
            keyword.update(value)
        else:
            keyword[parameter.name] = value
    return tuple(positional), keyword
