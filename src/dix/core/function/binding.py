from __future__ import annotations

import inspect

from dix.core.contract import ContractDefinition

from .errors import FunctionBindingError
from .models import FunctionBinding, FunctionDescriptor


def bind_function(
    function: FunctionDescriptor,
    contract: ContractDefinition,
) -> FunctionBinding:
    """Validate the minimal one-value Python invocation shape against one contract."""
    if not isinstance(function, FunctionDescriptor):
        raise FunctionBindingError("function must be a FunctionDescriptor")
    if not isinstance(contract, ContractDefinition):
        raise FunctionBindingError("contract must be a ContractDefinition")

    parameters = tuple(function.signature.parameters.values())
    if len(parameters) != 1:
        raise FunctionBindingError(
            f"contract-bound function must accept exactly one parameter: "
            f"{function.owner_id}.{function.id}{function.signature}"
        )
    parameter = parameters[0]
    if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
        call_style = "positional"
    elif parameter.kind in {
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }:
        call_style = "keyword"
    else:
        raise FunctionBindingError(
            f"contract-bound function parameter must not be variadic: "
            f"{function.owner_id}.{function.id}{function.signature}"
        )
    return FunctionBinding(
        function_id=function.id,
        owner_id=function.owner_id,
        contract=contract,
        parameter_name=parameter.name,
        call_style=call_style,
    )
