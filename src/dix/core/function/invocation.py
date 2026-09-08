from __future__ import annotations

from collections.abc import Callable

from dix.core.norn import (
    NornComponent,
    StrandExecutionError,
    StrandInputError,
    StrandOutputError,
)

from .errors import FunctionExecutionError, FunctionInputError, FunctionOutputError
from .models import FunctionBinding, FunctionRuntimeBinding


def bind_function_runtime(
    binding: FunctionBinding,
    target: Callable[..., object],
    *,
    norn: NornComponent,
) -> FunctionRuntimeBinding:
    """Bind one function implementation to its resolved strand in a local Norn scope."""
    norn.ensure_registered(binding.strand)
    handler_id = f"{binding.owner_id}.{binding.function_id}"

    def invoke_target(value: object) -> object:
        if binding.call_style == "positional":
            return target(value)
        return target(**{binding.parameter_name: value})

    norn.bind(
        binding.strand.id,
        handler_id=handler_id,
        handler=invoke_target,
    )
    return FunctionRuntimeBinding(function=binding, handler_id=handler_id)


async def invoke_function(
    binding: FunctionRuntimeBinding,
    value: object,
    *,
    norn: NornComponent,
) -> object:
    """Invoke one local function binding through its authoritative Norn strand."""
    try:
        return await norn.call(
            binding.function.strand.id,
            value,
            handler_id=binding.handler_id,
        )
    except StrandInputError as exc:
        raise FunctionInputError(binding.function.function_id, exc.issues) from exc
    except StrandOutputError as exc:
        raise FunctionOutputError(binding.function.function_id, exc.issues) from exc
    except StrandExecutionError as exc:
        cause = exc.__cause__ or exc
        raise FunctionExecutionError(binding.function.function_id) from cause
