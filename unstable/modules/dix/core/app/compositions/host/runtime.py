from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID, uuid4

from dix.core import (
    DatamodelComponent,
    ElementBinding,
    ElementProcessor,
    ModelDefinition,
    RegisteredModel,
)
from dix.core.application import (
    ApplicationComponent,
    ApplicationDescriptor,
    ApplicationFunctionDescriptor,
    ApplicationInstanceSpec,
)
from dix.core.composition import CompositionRuntimeContext


class ApplicationHostError(Exception):
    """Raised when a one-shot application call cannot satisfy its data contract."""


class Runtime:
    """Scoped host for inspecting and executing already loaded applications."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
        application: ApplicationComponent,
        datamodel: DatamodelComponent,
    ) -> None:
        self.context = context
        self.config = config
        self.application = application
        self.datamodel = datamodel
        self._input_models: dict[tuple[str, str], RegisteredModel] = {}
        self._input_overrides: dict[UUID, tuple[str, str, RegisteredModel]] = {}
        self._output_processors: dict[tuple[str, str], ElementProcessor] = {}

    def describe_application(self, application_id: str) -> ApplicationDescriptor:
        return self.application.describe_application(application_id)

    def describe_function(
        self,
        application_id: str,
        function_id: str,
    ) -> ApplicationFunctionDescriptor:
        return self.application.describe_function(application_id, function_id)

    def register_input_model(
        self,
        application_id: str,
        function_id: str,
        definition: ModelDefinition,
        elements: tuple[ElementBinding, ...] = (),
    ) -> UUID:
        descriptor = self.describe_function(application_id, function_id)
        expected = tuple(descriptor.signature.parameters)
        actual = tuple(definition.schema)
        if set(actual) != set(expected) or len(actual) != len(expected):
            raise ApplicationHostError(
                "input model fields must match the function parameters exactly: "
                f"expected={expected!r}, got={actual!r}"
            )
        registered = self.datamodel.register_model(definition, elements=elements)
        self._input_overrides[registered.uid] = (
            application_id,
            function_id,
            registered,
        )
        return registered.uid

    async def execute(
        self,
        application_id: str,
        function_id: str,
        args: Sequence[Any] | None = None,
        kwargs: Mapping[str, Any] | None = None,
        application_config: Mapping[str, object] | None = None,
        input_model_uid: UUID | None = None,
    ) -> Any:
        descriptor = self.describe_function(application_id, function_id)
        try:
            bound = descriptor.signature.bind(
                *(() if args is None else tuple(args)),
                **({} if kwargs is None else dict(kwargs)),
            )
        except TypeError as exc:
            raise ApplicationHostError(
                f"cannot bind input for '{application_id}.{function_id}': {exc}"
            ) from exc
        bound.apply_defaults()

        input_model = self._require_input_model(
            descriptor,
            input_model_uid=input_model_uid,
        )
        input_result = self.datamodel.instantiate(input_model, bound.arguments)
        if not input_result.compatible:
            raise ApplicationHostError(
                f"input is incompatible with '{application_id}.{function_id}': "
                f"{_format_issues(input_result.issues)}"
            )
        bound.arguments.update(input_result.values)

        execution_id = uuid4().hex
        owner_scope_id = f"application-host:{self.context.instance_id}:{execution_id}"
        instance_id = f"call-{execution_id}"
        created = False
        try:
            instance = self.application.create_instance(
                ApplicationInstanceSpec(
                    id=instance_id,
                    use=application_id,
                    config={} if application_config is None else application_config,
                    config_base_dir=self.context.config_base_dir,
                ),
                owner_scope_id=owner_scope_id,
            )
            created = True
            value = instance.api.require(function_id)(*bound.args, **bound.kwargs)
            if inspect.isawaitable(value):
                value = await value
            output_processor = self._require_output_processor(descriptor)
            output_result = output_processor.decode(value)
            if not output_result.compatible:
                raise ApplicationHostError(
                    f"output is incompatible with '{application_id}.{function_id}': "
                    f"{_format_issues(output_result.issues)}"
                )
            return output_result.value
        finally:
            if created:
                self.application.destroy_instance(owner_scope_id, instance_id)

    def _require_input_model(
        self,
        descriptor: ApplicationFunctionDescriptor,
        *,
        input_model_uid: UUID | None,
    ) -> RegisteredModel:
        if input_model_uid is not None:
            try:
                application_id, function_id, model = self._input_overrides[input_model_uid]
            except KeyError as exc:
                raise ApplicationHostError(
                    f"input model is not registered in this host: {input_model_uid}"
                ) from exc
            if (application_id, function_id) != (
                descriptor.application_id,
                descriptor.id,
            ):
                raise ApplicationHostError(
                    "input model is registered for a different application function"
                )
            return model

        key = (descriptor.application_id, descriptor.id)
        model = self._input_models.get(key)
        if model is None:
            model = self.datamodel.register_model(descriptor.contract.input_model)
            self._input_models[key] = model
        return model

    def _require_output_processor(
        self,
        descriptor: ApplicationFunctionDescriptor,
    ) -> ElementProcessor:
        key = (descriptor.application_id, descriptor.id)
        processor = self._output_processors.get(key)
        if processor is None:
            processor = self.datamodel.element.bind(
                descriptor.contract.output.element,
                self.datamodel.element.default_scope,
            )
            self._output_processors[key] = processor
        return processor


def _format_issues(issues: Sequence[object]) -> str:
    return "; ".join(str(issue) for issue in issues) or "unknown contract failure"
