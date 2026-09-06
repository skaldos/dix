from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol
from uuid import UUID

from dix.core import ElementBinding, ModelDefinition
from dix.core.application import (
    ApplicationDescriptor,
    ApplicationFunctionDescriptor,
    ApplicationRuntimeContext,
)


class HostApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Application facade over the scoped host composition."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        host: HostApi,
    ) -> None:
        self.context = context
        self.config = config
        self.host = host

    def describe_application(self, application_id: str) -> ApplicationDescriptor:
        return self.host.require("describe_application")(application_id)

    def describe_function(
        self,
        application_id: str,
        function_id: str,
    ) -> ApplicationFunctionDescriptor:
        return self.host.require("describe_function")(application_id, function_id)

    def register_input_model(
        self,
        application_id: str,
        function_id: str,
        definition: ModelDefinition,
        elements: tuple[ElementBinding, ...] = (),
    ) -> UUID:
        return self.host.require("register_input_model")(
            application_id,
            function_id,
            definition,
            elements,
        )

    async def execute(
        self,
        application_id: str,
        function_id: str,
        args: Sequence[Any] | None = None,
        kwargs: Mapping[str, Any] | None = None,
        application_config: Mapping[str, object] | None = None,
        input_model_uid: UUID | None = None,
    ) -> Any:
        return await self.host.require("execute")(
            application_id,
            function_id,
            args,
            kwargs,
            application_config,
            input_model_uid,
        )
