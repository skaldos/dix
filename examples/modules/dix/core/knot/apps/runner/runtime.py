from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from dix.core import StrandDescriptor
from dix.core.application import ApplicationRuntimeContext


class KnotApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Application facade over one private application-knot strand scope."""

    def __init__(
        self,
        *,
        context: ApplicationRuntimeContext,
        config: Mapping[str, object],
        knot: KnotApi,
    ) -> None:
        self.context = context
        self.config = config
        self.knot = knot

    def bind_application(
        self,
        application_id: str,
        application_config: Mapping[str, object] | None = None,
    ) -> tuple[StrandDescriptor, ...]:
        return self.knot.require("bind_application")(
            application_id,
            application_config,
        )

    def bind_function(
        self,
        strand_id: str,
        application_id: str,
        function_id: str,
        application_config: Mapping[str, object] | None = None,
    ) -> StrandDescriptor:
        return self.knot.require("bind_function")(
            strand_id,
            application_id,
            function_id,
            application_config,
        )

    def describe_strand(self, strand_id: str) -> StrandDescriptor:
        return self.knot.require("describe_strand")(strand_id)

    def strands(self) -> tuple[StrandDescriptor, ...]:
        return self.knot.require("strands")()

    async def call(self, strand_id: str, value: object) -> object:
        result = self.knot.require("call")(strand_id, value)
        return await result
