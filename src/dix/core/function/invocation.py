from __future__ import annotations

import inspect
from collections.abc import Callable

from dix.core.element import ElementComponent

from .errors import FunctionExecutionError, FunctionInputError, FunctionOutputError
from .models import FunctionBinding


async def invoke_function(
    binding: FunctionBinding,
    target: Callable[..., object],
    value: object,
    *,
    elements: ElementComponent,
) -> object:
    """Invoke one callable through the input and output elements of its contract."""
    input_processor = elements.bind(binding.contract.strand.input_element)
    input_result = input_processor.decode(value)
    if not input_result.compatible:
        raise FunctionInputError(binding.function_id, input_result.issues)

    try:
        if binding.call_style == "positional":
            result = target(input_result.value)
        else:
            result = target(**{binding.parameter_name: input_result.value})
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        raise FunctionExecutionError(binding.function_id) from exc

    output_processor = elements.bind(binding.contract.strand.output_element)
    output_result = output_processor.decode(result)
    if not output_result.compatible:
        raise FunctionOutputError(binding.function_id, output_result.issues)
    return output_result.value
